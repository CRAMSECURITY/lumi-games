import unittest, sqlite3, datetime as dt
import lumi_events as e
class Events(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:'); e.init(self.db); self.key=b'x'*32; self.today=dt.date(2026,11,28)
        self.addCleanup(self.db.close)
    def add(self,u,event,ago): e.record(self.db,self.key,u,event,self.today-dt.timedelta(days=ago),self.today)
    def test_dedup(self):
        self.add(1,'open',1); self.add(1,'open',1); self.add(1,'game',1)
        self.assertEqual(e.report(self.db,self.today,self.today-dt.timedelta(days=40))['dau'],1)
        self.assertEqual(self.db.execute('select count(*) from activity').fetchone()[0],2)
    def test_retention(self):
        self.add(1,'signup',8); self.add(2,'signup',8); self.add(1,'game',1)
        self.assertEqual(e.report(self.db,self.today,self.today-dt.timedelta(days=40))['retention']['7']['rate'],.5)
    def test_coverage(self): self.assertIsNone(e.report(self.db,self.today,self.today)['mau_30d'])
    def test_erase(self):
        self.add(1,'open',1); e.erase(self.db,self.key,1); self.assertEqual(self.db.execute('select count(*) from activity').fetchone()[0],0)
    def test_invalid(self):
        for event,ago in [('message',1),('open',-1),('open',90)]:
            with self.assertRaises(ValueError): self.add(1,event,ago)
    def test_prune(self):
        self.add(1,'open',89); e.prune(self.db,self.today+dt.timedelta(days=1)); self.assertEqual(self.db.execute('select count(*) from activity').fetchone()[0],0)
    def test_today_excluded(self):
        self.add(1,'open',0); self.assertEqual(e.report(self.db,self.today,self.today-dt.timedelta(days=40))['dau'],0)
