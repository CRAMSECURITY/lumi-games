import sqlite3, unittest
from lumi_data_lifecycle import expire_verification_material, purge_closed_support_events

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE profile_extras(user_id,verified,verification_status); CREATE TABLE verification_requests(user_id,status,submitted_at,created_at); CREATE TABLE admin_events(type,ref_id); CREATE TABLE support_tickets(id,status,updated_at);''')
    def test_expired_review(self):
        self.db.executescript("INSERT INTO profile_extras VALUES(1,0,'review'),(2,0,'review'),(3,1,'approved'); INSERT INTO verification_requests VALUES(1,'review',NULL,'2000-01-01'),(2,'review',datetime('now'), '2000-01-01'),(3,'approved',NULL,'2000-01-01'); INSERT INTO admin_events VALUES('verification',1),('verification',2),('ticket',1);")
        expire_verification_material(self.db)
        self.assertEqual(self.db.execute('SELECT user_id FROM verification_requests').fetchall(),[(2,)])
        self.assertEqual(self.db.execute('SELECT verification_status FROM profile_extras ORDER BY user_id').fetchall(),[('none',),('review',),('approved',)])
        self.assertEqual(self.db.execute('SELECT * FROM admin_events').fetchall(),[('verification',2),('ticket',1)])
    def test_support_scope(self):
        self.db.executescript("INSERT INTO support_tickets VALUES(1,'closed','2000-01-01'),(2,'open','2000-01-01'),(3,'closed',datetime('now')); INSERT INTO admin_events VALUES('ticket',1),('ticket',2),('ticket',3),('verification',1);")
        purge_closed_support_events(self.db)
        self.assertEqual(self.db.execute('SELECT * FROM admin_events').fetchall(),[('ticket',2),('ticket',3),('verification',1)])
