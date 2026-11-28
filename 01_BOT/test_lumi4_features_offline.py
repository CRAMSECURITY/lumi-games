"""Offline: production bot not imported, no Telegram or network required."""
import sqlite3
from lumi_test_sqlite import patch_sqlite_connect
patch_sqlite_connect()
import tempfile
from pathlib import Path
from datetime import date, timedelta
from lumi_referrals import init_referrals, register_referral, confirm_registration, has_referral_frame, referral_count, delete_referral_data
from lumi_daily import init_daily_rewards, claim_daily_reward, daily_reward_status

with tempfile.TemporaryDirectory() as directory:
    db = sqlite3.connect(str(Path(directory) / 'test.db'))
    try:
        db.execute('CREATE TABLE profiles(user_id INTEGER PRIMARY KEY, age INTEGER NOT NULL)')
        db.execute("CREATE TABLE account_suspensions(user_id INTEGER, expires_at TEXT)")
        init_referrals(db); init_daily_rewards(db)
        db.execute('INSERT INTO profiles VALUES(1,20)')
        assert not register_referral(db,1,1)
        assert not register_referral(db,2,3)
        assert register_referral(db,2,1)
        assert not register_referral(db,2,1)
        assert not register_referral(db,2,3)
        db.execute('INSERT INTO profiles VALUES(2,19)')
        assert confirm_registration(db,2) == (1,1,False)
        assert confirm_registration(db,2) is None
        for guest in (3,4):
            assert register_referral(db,guest,1)
            db.execute('INSERT INTO profiles VALUES(?,19)',(guest,))
            result = confirm_registration(db,guest)
            assert result[0] == 1
        assert referral_count(db,1)==3
        assert has_referral_frame(db,1)
        assert not register_referral(db,5,5)
        today=date(2026,11,25)
        result=claim_daily_reward(db,1,today)
        assert result == {'awarded':True,'xp':15,'streak':1}
        assert claim_daily_reward(db,1,today)['awarded'] is False
        assert daily_reward_status(db,1,today)['claimed_today']
        for i in range(1,7):
            result=claim_daily_reward(db,1,today+timedelta(days=i))
        assert result=={'awarded':True,'xp':35,'streak':7}
        assert claim_daily_reward(db,1,today+timedelta(days=8))['streak']==1
        assert claim_daily_reward(db,1,today+timedelta(days=7))['awarded'] is False
        delete_referral_data(db,1)
        assert referral_count(db,1)==0
        assert not has_referral_frame(db,1)
        db.execute('DELETE FROM lumi_daily_rewards WHERE user_id=1')
        assert daily_reward_status(db,1)['total_claims']==0
        db.commit()
    finally:
        db.close()
print('PASS referrals: registration, self-invite, deduplication, 3-person frame, deletion')
print('PASS daily: once UTC day, 7-day streak, missed day, past day, deletion')
