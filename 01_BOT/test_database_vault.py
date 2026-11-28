import os
import sqlite3
import stat
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from lumi_database_vault import connect_private, protect_database_files

class VaultTests(unittest.TestCase):
    def test_pragmas_and_existing_data(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'lumi.db'
            with closing(sqlite3.connect(p)) as db:
                db.execute('CREATE TABLE profiles(name TEXT)')
                db.execute('INSERT INTO profiles VALUES (?)', ('existing',)); db.commit()
            with closing(connect_private(p)) as db:
                self.assertEqual(db.execute('SELECT name FROM profiles').fetchone()[0], 'existing')
                for pragma, expected in [('secure_delete',1),('trusted_schema',0),('temp_store',2)]:
                    self.assertEqual(db.execute('PRAGMA '+pragma).fetchone()[0],expected)
                self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok')
    @unittest.skipUnless(os.name=='posix','POSIX permissions')
    def test_private_main_and_wal(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'lumi.db'
            with closing(connect_private(p)) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE t(x)'); db.commit()
                for suffix in ('','-wal','-shm'):
                    f=Path(str(p)+suffix); os.chmod(f,0o644)
                protect_database_files(p)
                for suffix in ('','-wal','-shm'):
                    self.assertEqual(stat.S_IMODE(Path(str(p)+suffix).stat().st_mode),0o600)
    @unittest.skipUnless(os.name=='posix','POSIX links')
    def test_symlink_and_hardlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'lumi.db'; target=Path(d)/'other'; target.write_text('untouched')
            p.symlink_to(target)
            with self.assertRaises(RuntimeError): connect_private(p)
            p.unlink(); os.link(target,p)
            with self.assertRaises(RuntimeError): connect_private(p)
            self.assertEqual(target.read_text(),'untouched')
    def test_deleted_record_not_in_clean_database(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'lumi.db'; marker='PRIVATE_TEST_MARKER_123456789'
            with closing(connect_private(p)) as db:
                db.execute('CREATE TABLE t(x)'); db.execute('INSERT INTO t VALUES (?)',(marker,)); db.commit()
                self.assertIn(marker.encode(),p.read_bytes())
                db.execute('DELETE FROM t'); db.commit()
                self.assertNotIn(marker.encode(),p.read_bytes())
