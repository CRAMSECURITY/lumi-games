from contextlib import closing
import sqlite3, unittest
from lumi_global_ban import init_sync
class TestSync(unittest.TestCase):
    def test_seed_and_order(self):
        with closing(sqlite3.connect(':memory:')) as db, db:
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('CREATE TABLE account_suspensions(user_id INTEGER PRIMARY KEY, expires_at TEXT)')
            db.execute('INSERT INTO account_suspensions VALUES(1,NULL)')
            init_sync(db);init_sync(db)
            db.execute('UPDATE account_suspensions SET expires_at="2030-01-01 00:00:00" WHERE user_id=1')
            db.execute('DELETE FROM account_suspensions WHERE user_id=1')
            self.assertEqual(db.execute('SELECT seq,uid,expires FROM ban_sync ORDER BY seq').fetchall(),[(1,1,-1),(2,1,1893456000),(3,1,0)])
    def test_rollback(self):
        db=sqlite3.connect(':memory:');db.execute('CREATE TABLE account_suspensions(user_id INTEGER PRIMARY KEY, expires_at TEXT)');init_sync(db);db.commit()
        db.execute('INSERT INTO account_suspensions VALUES(2,NULL)');db.rollback()
        self.assertEqual(db.execute('SELECT COUNT(*) FROM ban_sync').fetchone()[0],0);db.close()
if __name__=='__main__':unittest.main()
