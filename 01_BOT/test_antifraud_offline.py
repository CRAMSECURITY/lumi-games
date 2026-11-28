import sqlite3, unittest, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from lumi_referrals import init_referrals, register_referral, confirm_registration
from lumi_antifraud import record_report_once

class FraudTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'db'; self.db=sqlite3.connect(self.path); self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE profiles(user_id INTEGER PRIMARY KEY, age INTEGER); INSERT INTO profiles VALUES(1,20),(2,20); CREATE TABLE account_suspensions(user_id INTEGER, expires_at TEXT); CREATE TABLE reports(id INTEGER PRIMARY KEY,reporter_id INTEGER,reported_id INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP);''')
        init_referrals(self.db); self.db.commit()
    def test_suspended_inviter(self):
        self.db.execute('INSERT INTO account_suspensions VALUES(1,NULL)'); self.assertFalse(register_referral(self.db,3,1))
    def test_suspended_invitee(self):
        self.db.execute('INSERT INTO account_suspensions VALUES(3,NULL)'); self.assertFalse(register_referral(self.db,3,1))
    def test_suspended_after_attribution(self):
        self.assertTrue(register_referral(self.db,3,1)); self.db.execute('INSERT INTO profiles VALUES(3,20)'); self.db.execute('INSERT INTO account_suspensions VALUES(1,NULL)'); self.assertIsNone(confirm_registration(self.db,3))
    def test_cap_parallel(self):
        def attempt(uid):
            db=sqlite3.connect(self.path,timeout=10)
            try:
                with db: return register_referral(db,uid,1)
            finally: db.close()
        with ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(attempt,range(10,50)))
        self.assertEqual(sum(results),30)
        self.db.execute("UPDATE lumi_referrals SET invited_at=datetime('now','-1 day')"); self.assertTrue(register_referral(self.db,100,1))
    def test_reports(self):
        self.db.execute('BEGIN IMMEDIATE'); self.assertIsNotNone(record_report_once(self.db,1,2)); self.assertIsNone(record_report_once(self.db,1,2)); self.assertIsNotNone(record_report_once(self.db,2,1)); self.assertIsNone(record_report_once(self.db,1,1)); self.db.execute("UPDATE reports SET created_at=datetime('now','-25 hours')"); self.assertIsNotNone(record_report_once(self.db,1,2))
    def test_expired_suspension(self):
        self.db.execute("INSERT INTO account_suspensions VALUES(1,datetime('now','-1 day'))"); self.assertTrue(register_referral(self.db,3,1))
if __name__=='__main__': unittest.main()
