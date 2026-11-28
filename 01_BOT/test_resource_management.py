import sqlite3, tempfile, unittest
from pathlib import Path
from contextlib import closing
from lumi_database_vault import connect_private

class ResourceTests(unittest.TestCase):
    def test_commit_and_close(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'db'
            with connect_private(p) as db:
                db.execute('CREATE TABLE t(x)')
                db.execute('INSERT INTO t VALUES (1)')
            with self.assertRaises(sqlite3.ProgrammingError): db.execute('SELECT 1')
            with connect_private(p) as other:
                self.assertEqual(other.execute('SELECT x FROM t').fetchall(),[(1,)])
    def test_rollback_and_close(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'db'
            with connect_private(p) as db: db.execute('CREATE TABLE t(x)')
            with self.assertRaises(ValueError):
                with connect_private(p) as db:
                    db.execute('INSERT INTO t VALUES (1)')
                    raise ValueError('rollback')
            with self.assertRaises(sqlite3.ProgrammingError): db.execute('SELECT 1')
            with connect_private(p) as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM t').fetchone(),(0,))
    def test_repeated_connections(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'db'
            connections=[]
            for i in range(250):
                with connect_private(p) as db: db.execute('SELECT 1'); connections.append(db)
            for db in connections:
                with self.assertRaises(sqlite3.ProgrammingError): db.execute('SELECT 1')
    def test_explicit_closing_compatible(self):
        with tempfile.TemporaryDirectory() as d:
            with closing(connect_private(Path(d)/'db')) as db, db: db.execute('CREATE TABLE t(x)')
            with self.assertRaises(sqlite3.ProgrammingError): db.execute('SELECT 1')
