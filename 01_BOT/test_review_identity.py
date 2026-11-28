import sqlite3
import unittest
from lumi_verification import new_review_id, parse_review_callback, decide_review

class ReviewIdentityTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:', factory=sqlite3.Connection)
        self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE profiles(user_id INTEGER PRIMARY KEY);
        CREATE TABLE verification_requests(user_id INTEGER PRIMARY KEY,status TEXT,video_note_id TEXT,challenge TEXT,expires_at TEXT,review_id TEXT);
        CREATE TABLE profile_extras(user_id INTEGER PRIMARY KEY,verified INTEGER,verification_status TEXT);
        CREATE TABLE security_audit(actor INTEGER,action TEXT,target INTEGER);
        INSERT INTO profiles VALUES(1);''')
        self.old=new_review_id(); self.current=new_review_id()
        self.db.execute("INSERT INTO verification_requests VALUES(1,'review','clip','task',NULL,?)",(self.current,))
    def test_old_button(self):
        self.assertFalse(decide_review(self.db,1,True,9,self.old))
        self.assertEqual(self.db.execute('SELECT status FROM verification_requests').fetchone()[0],'review')
    def test_current_once(self):
        self.assertTrue(decide_review(self.db,1,True,9,self.current))
        self.assertFalse(decide_review(self.db,1,False,9,self.current))
        self.assertEqual(self.db.execute('SELECT verified FROM profile_extras').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM security_audit').fetchone()[0],1)
    def test_missing_profile(self):
        self.db.execute('DELETE FROM profiles')
        self.assertFalse(decide_review(self.db,1,True,9,self.current))
    def test_callback(self):
        self.assertEqual(parse_review_callback(f'vcheck:yes:1:{self.current}'),(1,True,self.current))
        for bad in ['vcheck:yes:1','vcheck:no:0:'+self.current,'vcheck:yes:1:bad','vcheck:yes:9223372036854775808:'+self.current]:
            with self.assertRaises(ValueError): parse_review_callback(bad)
    def test_rollback(self):
        self.db.commit(); self.db.execute('DROP TABLE security_audit')
        with self.assertRaises(sqlite3.OperationalError):
            with self.db: decide_review(self.db,1,True,9,self.current)
        self.assertEqual(self.db.execute('SELECT status FROM verification_requests').fetchone()[0],'review')
