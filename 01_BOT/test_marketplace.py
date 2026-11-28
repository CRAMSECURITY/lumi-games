import sqlite3, unittest, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from lumi_marketplace import init_demo, purchase

class MarketplaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'demo.db'
        self.db=sqlite3.connect(self.path,factory=sqlite3.Connection); self.addCleanup(self.db.close)
        init_demo(self.db)
        with self.db: self.db.execute('INSERT INTO demo_wallet VALUES(1,200)')
    def balance(self): return self.db.execute('SELECT balance FROM demo_wallet WHERE uid=1').fetchone()[0]
    def test_purchase(self):
        self.assertEqual(purchase(self.db,1,'aurora_frame','a'),'purchased'); self.assertEqual(self.balance(),100)
    def test_replay(self):
        purchase(self.db,1,'aurora_frame','a'); self.assertEqual(purchase(self.db,1,'aurora_frame','a'),'replayed'); self.assertEqual(self.balance(),100)
    def test_duplicate(self):
        purchase(self.db,1,'aurora_frame','a'); self.assertEqual(purchase(self.db,1,'aurora_frame','b'),'owned'); self.assertEqual(self.balance(),100)
    def test_conflict(self):
        purchase(self.db,1,'aurora_frame','a')
        with self.assertRaises(ValueError): purchase(self.db,1,'violet_badge','a')
        self.assertEqual(self.balance(),100)
    def test_insufficient(self):
        purchase(self.db,1,'aurora_frame','a'); self.assertEqual(purchase(self.db,1,'obsidian_glow','b'),'insufficient'); self.assertEqual(self.balance(),100)
    def test_invalid(self):
        for uid,sku,rid in [(True,'aurora_frame','a'),(1,'unknown','a'),(1,'aurora_frame','!')]:
            with self.assertRaises(ValueError): purchase(self.db,uid,sku,rid)
        self.assertEqual(self.balance(),200)
    def test_rollback(self):
        with self.db: self.db.execute("CREATE TRIGGER fail BEFORE INSERT ON demo_orders BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError): purchase(self.db,1,'aurora_frame','a')
        self.assertEqual(self.balance(),200)
    def test_parallel(self):
        def buy(i):
            from contextlib import closing
            with closing(sqlite3.connect(self.path,timeout=10,factory=sqlite3.Connection)) as db:
                return purchase(db,1,'aurora_frame',str(i))
        with ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(buy,range(32)))
        self.assertEqual(results.count('purchased'),1); self.assertEqual(self.balance(),100)
if __name__=='__main__': unittest.main()
