import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from lumi_observability import probe

class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'test.db'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE profiles(user_id INTEGER)')
            db.execute('CREATE TABLE lumi_ops_daily(day TEXT, metric TEXT, count INTEGER)')
            db.execute('INSERT INTO profiles VALUES(123456789)')
    def test_ok_and_private(self):
        before = self.path.read_bytes()
        result = probe(self.path, slow_ms=60000)
        self.assertEqual(result['status'], 'ok')
        self.assertNotIn('123456789', str(result))
        self.assertEqual(before, self.path.read_bytes())
    def test_missing(self):
        path = self.path.with_name('missing.db')
        self.assertEqual(probe(path), {'status':'unavailable'})
        self.assertFalse(path.exists())
    def test_errors(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO lumi_ops_daily VALUES(date('now'),'error',20)")
        self.assertEqual(probe(self.path)['status'], 'degraded')
    def test_bad_schema(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DROP TABLE profiles')
        self.assertEqual(probe(self.path), {'status':'unavailable'})
    def test_threshold(self):
        with self.assertRaises(ValueError): probe(self.path, slow_ms=0)
    def test_corrupt(self):
        self.path.write_bytes(b'bad database')
        self.assertEqual(probe(self.path), {'status':'unavailable'})
