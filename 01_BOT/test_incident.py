import unittest
import tempfile
import sqlite3
import io
import json
from pathlib import Path
from contextlib import redirect_stdout, closing
from lumi_incident import classify, main

class IncidentTests(unittest.TestCase):
    def test_healthy(self):
        self.assertEqual(classify({'status':'ok'})['severity'], 'none')
    def test_degraded(self):
        self.assertEqual(classify({'status':'degraded'})['severity'], 'warning')
    def test_unknown(self):
        self.assertEqual(classify({})['severity'], 'critical')
    def test_no_disclosure(self):
        self.assertNotIn('secret', str(classify({'status':'unavailable', 'exception':'secret'})))
    def test_missing_cli(self):
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main([str(Path(d)/'private.db')]), 2)
            self.assertEqual(json.loads(out.getvalue())['event'], 'database_unavailable')
            self.assertNotIn('private.db', out.getvalue())
    def test_degraded_cli(self):
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()) as out:
            p=Path(d)/'test.db'
            with closing(sqlite3.connect(p)) as db, db:
                db.execute('CREATE TABLE profiles(user_id INTEGER)')
                db.execute('CREATE TABLE lumi_ops_daily(day TEXT, metric TEXT, count INTEGER)')
                db.execute("INSERT INTO lumi_ops_daily VALUES(date('now'),'error',20)")
            before=p.read_bytes()
            self.assertEqual(main([str(p)]), 1)
            self.assertEqual(json.loads(out.getvalue())['severity'], 'warning')
            self.assertEqual(before,p.read_bytes())
