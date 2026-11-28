import unittest, sqlite3, datetime as dt
import lumi_analytics_live as a
class Live(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:'); self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE profiles(user_id INTEGER PRIMARY KEY)'); self.db.execute('INSERT INTO profiles VALUES(1),(2)'); a.init(self.db); self.today=dt.date(2026,11,28)
    def test_default_off(self):
        a.record(self.db,1,self.today); self.assertEqual(self.db.execute('SELECT count(*) FROM lumi_analytics_activity').fetchone()[0],0)
    def test_dedup(self):
        self.assertTrue(a.opt_in(self.db,1)); a.record(self.db,1,self.today); a.record(self.db,1,self.today); self.assertEqual(self.db.execute('SELECT count(*) FROM lumi_analytics_activity').fetchone()[0],1)
    def test_delete(self):
        a.opt_in(self.db,1); a.record(self.db,1,self.today); self.db.execute('DELETE FROM profiles WHERE user_id=1'); a.record(self.db,1,self.today); self.assertEqual(self.db.execute('SELECT count(*) FROM lumi_analytics_activity').fetchone()[0],0); self.assertEqual(self.db.execute('SELECT count(*) FROM lumi_analytics_consent').fetchone()[0],0)
    def test_opt_out(self):
        a.opt_in(self.db,1); a.record(self.db,1,self.today); a.opt_out(self.db,1); a.record(self.db,1,self.today); self.assertEqual(self.db.execute('SELECT count(*) FROM lumi_analytics_activity').fetchone()[0],0)
    def test_report_and_prune(self):
        a.opt_in(self.db,1); a.record(self.db,1,self.today-dt.timedelta(days=1)); a.record(self.db,1,self.today-dt.timedelta(days=90)); a.prune(self.db,self.today); self.assertEqual(a.report(self.db,self.today)['observed_1d'],1); self.assertEqual(self.db.execute('SELECT count(*) FROM lumi_analytics_activity').fetchone()[0],1)
    def test_unknown(self): self.assertFalse(a.opt_in(self.db,99))
