from contextlib import closing
import tempfile, sqlite3, unittest
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from lumi_restore import restore
class TestRestore(unittest.TestCase):
    def test_restore(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);key=Fernet.generate_key();db=sqlite3.connect(':memory:');db.execute('CREATE TABLE t(x)');db.execute('INSERT INTO t VALUES(42)');db.commit();(p/'backup').write_bytes(Fernet(key).encrypt(db.serialize()));db.close()
            with self.assertRaises(InvalidToken):restore(p/'backup',p/'bad',Fernet.generate_key())
            self.assertFalse((p/'bad').exists());restore(p/'backup',p/'new',key)
            with closing(sqlite3.connect(p/'new')) as db, db:self.assertEqual(db.execute('SELECT x FROM t').fetchone(),(42,))
            with self.assertRaises(FileExistsError):restore(p/'backup',p/'new',key)
if __name__=='__main__':unittest.main()
