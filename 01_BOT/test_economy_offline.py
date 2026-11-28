import sqlite3
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import unittest
from lumi_economy import eligible_for_reward, pair_battles_today, claim_training
from lumi_daily import init_daily_rewards, claim_daily_reward
from lumi_referrals import init_referrals, register_referral, confirm_registration

class EconomyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'test.db'
        self.db = sqlite3.connect(self.path, factory=sqlite3.Connection)
        self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE profiles(user_id INTEGER PRIMARY KEY, age INTEGER);
            INSERT INTO profiles VALUES(1,20),(2,19),(3,17);
            CREATE TABLE account_suspensions(user_id INTEGER, expires_at TEXT);
            CREATE TABLE arena_heroes(user_id INTEGER PRIMARY KEY,last_daily TEXT,xp INTEGER DEFAULT 0);
            INSERT INTO arena_heroes(user_id) VALUES(1);
            CREATE TABLE arena_challenges(id INTEGER PRIMARY KEY,challenger INTEGER,defender INTEGER);
            CREATE TABLE arena_battle_log(challenge_id INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP);''')
        init_daily_rewards(self.db); init_referrals(self.db); self.db.commit()
    def test_eligibility(self):
        self.assertTrue(eligible_for_reward(self.db,1)); self.assertFalse(eligible_for_reward(self.db,3)); self.assertFalse(eligible_for_reward(self.db,99))
        self.db.execute('INSERT INTO account_suspensions VALUES(1,NULL)'); self.assertFalse(eligible_for_reward(self.db,1))
        self.db.execute("UPDATE account_suspensions SET expires_at=datetime('now','-1 minute')"); self.assertTrue(eligible_for_reward(self.db,1))
    def test_pair_count(self):
        self.db.executescript('INSERT INTO arena_challenges VALUES(1,1,2),(2,2,1),(3,1,2),(4,1,2); INSERT INTO arena_battle_log(challenge_id) VALUES(1),(2),(3); INSERT INTO arena_battle_log VALUES(4,datetime(\'now\',\'-1 day\'));')
        self.assertEqual(pair_battles_today(self.db,1,2),3); self.assertEqual(pair_battles_today(self.db,2,1),3)
    def test_training_clock(self):
        self.assertTrue(claim_training(self.db,1,date(2026,11,28)))
        self.assertFalse(claim_training(self.db,1,date(2026,11,28)))
        self.assertFalse(claim_training(self.db,1,date(2026,11,27)))
        self.assertTrue(claim_training(self.db,1,date(2026,11,29)))
    def test_parallel_claims(self):
        def attempt(_):
            db=sqlite3.connect(self.path,timeout=10)
            try:
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    training=claim_training(db,1,date(2026,11,28))
                    gift=claim_daily_reward(db,1,date(2026,11,28))['xp']
                    db.execute('UPDATE arena_heroes SET xp=xp+? WHERE user_id=1',(10*training+gift,))
                    return training,gift
            finally: db.close()
        with ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(attempt,range(32)))
        self.assertEqual(sum(r[0] for r in results),1); self.assertEqual(sum(r[1] for r in results),15)
        self.assertEqual(self.db.execute('SELECT xp FROM arena_heroes').fetchone()[0],25)
    def test_rollback(self):
        with self.assertRaises(RuntimeError):
            with self.db:
                self.db.execute('BEGIN IMMEDIATE'); claim_training(self.db,1); claim_daily_reward(self.db,1); raise RuntimeError()
        self.assertIsNone(self.db.execute('SELECT last_daily FROM arena_heroes').fetchone()[0]); self.assertEqual(self.db.execute('SELECT count(*) FROM lumi_daily_rewards').fetchone()[0],0)
    def test_referrals(self):
        self.assertFalse(register_referral(self.db,4,2**63)); self.assertFalse(register_referral(self.db,True,2))
        self.assertTrue(register_referral(self.db,4,1)); self.db.execute('INSERT INTO profiles VALUES(4,20)')
        self.assertEqual(confirm_registration(self.db,4),(1,1,False)); self.assertIsNone(confirm_registration(self.db,4))

if __name__=='__main__': unittest.main(verbosity=2)
