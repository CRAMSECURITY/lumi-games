import sqlite3, unittest, tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import lumi_clubs as c

class Clubs(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'test.sqlite'
        self.db=sqlite3.connect(self.path); self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE profiles(user_id INTEGER PRIMARY KEY, age INTEGER); CREATE TABLE account_suspensions(user_id INTEGER, expires_at TEXT);')
        self.db.executemany('INSERT INTO profiles VALUES(?,25)',[(i,) for i in range(1,33)])
        c.init(self.db); self.db.commit()
    def test_join_leave(self):
        e=c.act(self.db,1)[0]
        self.assertEqual(c.act(self.db,1,'join','games',e)[2],'joined')
        self.assertEqual(c.act(self.db,1,'join','games',e)[2],'owned')
        self.assertEqual(c.act(self.db,1,'leave','games',e)[1],[])
    def test_limit(self):
        e=c.act(self.db,1)[0]
        for k in list(c.CLUBS)[:3]: c.act(self.db,1,'join',k,e)
        self.assertEqual(c.act(self.db,1,'join','art',e)[2],'limit')
    def test_isolation(self):
        e=c.act(self.db,1)[0]; c.act(self.db,2)
        self.assertIsNone(c.act(self.db,2,'join','games',e))
    def test_blocked(self):
        e=c.act(self.db,1)[0]; self.db.execute('INSERT INTO account_suspensions VALUES(1,NULL)'); self.db.commit()
        self.assertIsNone(c.act(self.db,1,'join','games',e))
        self.assertIsNone(c.act(self.db,99))
    def test_delete(self):
        e=c.act(self.db,1)[0]; c.act(self.db,1,'join','games',e)
        self.db.execute('DELETE FROM profiles WHERE user_id=1'); self.db.execute('INSERT INTO profiles VALUES(1,25)'); self.db.commit()
        self.assertEqual(c.act(self.db,1)[1],[]); self.assertIsNone(c.act(self.db,1,'join','games',e))
    def test_invalid(self):
        with self.assertRaises(ValueError): c.act(self.db,True)
        with self.assertRaises(ValueError): c.act(self.db,1,'join','invalid','x')
    def test_concurrent_capacity(self):
        def join(i):
            with sqlite3.connect(self.path,timeout=10) as db:
                return c.act(db,i,'join','games',c.act(db,i)[0])[2]
        with patch.object(c,'CAPACITY',5), ThreadPoolExecutor(max_workers=8) as pool:
            result=list(pool.map(join,range(1,33)))
        self.assertEqual(result.count('joined'),5); self.assertEqual(result.count('full'),27)

    def test_activity_membership_and_repeat(self):
        e=c.act(self.db,1)[0]; w=c.week_key()
        self.assertIsNone(c.activities(self.db,1,e,'games',w))
        c.act(self.db,1,'join','games',e)
        for _ in range(3): self.assertEqual(c.activities(self.db,1,e,'games',w)[2],['games'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM lumi_club_activity').fetchone()[0],1)
    def test_activity_old_week_and_epoch(self):
        e=c.act(self.db,1)[0]; c.act(self.db,1,'join','games',e)
        self.assertIsNone(c.activities(self.db,1,e,'games','2000-01-03'))
        self.assertIsNone(c.activities(self.db,1,'wrong'))
    def test_activity_leave_and_delete(self):
        e=c.act(self.db,1)[0]; c.act(self.db,1,'join','games',e)
        c.activities(self.db,1,e,'games',c.week_key()); c.act(self.db,1,'leave','games',e)
        self.assertEqual(c.activities(self.db,1,e)[2],[])
        c.act(self.db,1,'join','games',e); c.activities(self.db,1,e,'games',c.week_key())
        self.db.execute('DELETE FROM profiles WHERE user_id=1'); self.db.commit()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM lumi_club_activity').fetchone()[0],0)
    def test_activity_blocked(self):
        e=c.act(self.db,1)[0]; c.act(self.db,1,'join','games',e)
        self.db.execute('INSERT INTO account_suspensions VALUES(1,NULL)'); self.db.commit()
        self.assertIsNone(c.activities(self.db,1,e,'games',c.week_key()))
