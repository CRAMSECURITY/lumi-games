import sqlite3
import unittest
from lumi_antifraud import isolate_pair

class PairIsolationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:', factory=sqlite3.Connection)
        self.addCleanup(self.db.close)
        self.db.executescript('''
        CREATE TABLE blocks(user_id,blocked_id, UNIQUE(user_id,blocked_id));
        CREATE TABLE arena_challenges(challenger,defender,status,resolved_at);
        CREATE TABLE game_sessions(user_a,user_b);
        CREATE TABLE active_chats(user_id,peer_id);
        CREATE TABLE contact_requests(requester_id,recipient_id);
        INSERT INTO arena_challenges VALUES(1,2,'pending',NULL),(2,1,'pending',NULL),(1,3,'pending',NULL);
        INSERT INTO game_sessions VALUES(1,2),(2,1),(1,3);
        INSERT INTO active_chats VALUES(1,2),(2,1),(1,3);
        INSERT INTO contact_requests VALUES(1,2),(2,1),(1,3);
        ''')
    def test_isolation_and_unrelated_pair(self):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            isolate_pair(self.db,1,2)
            isolate_pair(self.db,1,2)
        for table in ('game_sessions','active_chats','contact_requests'):
            self.assertEqual(self.db.execute('SELECT * FROM '+table).fetchall(),[(1,3)])
        self.assertEqual(self.db.execute('SELECT status FROM arena_challenges ORDER BY rowid').fetchall(), [('cancelled',),('cancelled',),('pending',)])
        self.assertEqual(self.db.execute('SELECT * FROM blocks').fetchall(),[(1,2)])
    def test_rollback(self):
        with self.assertRaises(RuntimeError):
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                isolate_pair(self.db,1,2)
                raise RuntimeError('simulated failure')
        self.assertEqual(self.db.execute('SELECT count(*) FROM active_chats').fetchone()[0],3)
        self.assertEqual(self.db.execute('SELECT count(*) FROM blocks').fetchone()[0],0)
    def test_requires_transaction(self):
        with self.assertRaises(ValueError): isolate_pair(self.db,1,2)
