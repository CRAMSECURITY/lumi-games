from contextlib import closing
import unittest, tempfile, sqlite3, os
from pathlib import Path
from datetime import datetime, timezone
from cryptography.fernet import Fernet, InvalidToken
from lumi_backup_policy import create_daily_backup

class BackupPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.db=self.root/'source.db'; self.dir=self.root/'copies'; self.dir.mkdir()
        with closing(sqlite3.connect(self.db)) as db, db: db.execute('CREATE TABLE private_data(x)'); db.execute('INSERT INTO private_data VALUES(42)')
        self.key=Fernet.generate_key(); self.now=datetime(2026,11,28,tzinfo=timezone.utc)
        self.old=self.dir/'lumi_2026-11-01.db.enc'; self.old.write_bytes(b'old')
    def run_backup(self,key=None): return create_daily_backup(self.db,self.dir,self.key if key is None else key,now=self.now)
    def test_valid_then_prune(self):
        p=self.run_backup(); self.assertFalse(self.old.exists()); self.assertEqual(self.run_backup(),p)
        if os.name=='posix': self.assertEqual(self.dir.stat().st_mode & 0o777,0o700)
    def test_invalid_key_preserves_old(self):
        with self.assertRaises(ValueError): self.run_backup(b'invalid')
        self.assertTrue(self.old.exists())
    def test_corrupt_today_preserves_old(self):
        (self.dir/'lumi_2026-11-28.db.enc').write_bytes(b'corrupt')
        with self.assertRaises(InvalidToken): self.run_backup()
        self.assertTrue(self.old.exists())
    def test_wrong_key_preserves_old(self):
        self.run_backup(); self.old.write_bytes(b'old')
        with self.assertRaises(InvalidToken): self.run_backup(Fernet.generate_key())
        self.assertTrue(self.old.exists())
    def test_legacy_not_deleted(self):
        p=self.dir/'lumi_2026-11-01.db'; p.write_bytes(b'legacy'); self.run_backup(); self.assertTrue(p.exists())
