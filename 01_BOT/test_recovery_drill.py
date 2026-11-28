import sqlite3, tempfile, unittest
from pathlib import Path
from contextlib import closing
from cryptography.fernet import Fernet, InvalidToken
from lumi_recovery_drill import drill, REQUIRED
from lumi_restore import restore

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.key = Fernet.generate_key(); self.source = self.root/'backup.enc'
    def snapshot(self, complete=True):
        with closing(sqlite3.connect(':memory:')) as db:
            for table, columns in REQUIRED.items():
                if not complete and table == 'premium_orders': continue
                db.execute(f'CREATE TABLE {table} ('+', '.join(sorted(columns))+')')
            self.source.write_bytes(Fernet(self.key).encrypt(db.serialize()))
    def test_valid(self):
        self.snapshot(); self.assertEqual(drill(self.source,self.key,self.root),3); self.assertEqual(list(self.root.iterdir()),[self.source])
    def test_incomplete(self):
        self.snapshot(False)
        with self.assertRaises(ValueError): drill(self.source,self.key,self.root)
        self.assertEqual(list(self.root.iterdir()),[self.source])
    def test_wrong_key(self):
        self.snapshot()
        with self.assertRaises(InvalidToken): drill(self.source,Fernet.generate_key(),self.root)
        self.assertEqual(list(self.root.iterdir()),[self.source])
    def test_sidecars(self):
        self.snapshot(); dest=self.root/'new.sqlite'
        for suffix in ('-wal','-shm','-journal'):
            side=Path(str(dest)+suffix); side.touch()
            with self.assertRaises(FileExistsError): restore(self.source,dest,self.key)
            self.assertFalse(dest.exists()); side.unlink()
