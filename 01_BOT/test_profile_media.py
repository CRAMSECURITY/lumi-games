import sqlite3, unittest
from types import SimpleNamespace
from lumi_profile_media import init_media_identity, media_available, media_identity

class ProfileMediaTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE profiles(user_id INTEGER PRIMARY KEY, photo_id TEXT, video_id TEXT)')
        self.db.execute("INSERT INTO profiles VALUES(1,'old-photo',NULL)")
        init_media_identity(self.db)
        self.db.execute("UPDATE profiles SET media_unique_id='stable' WHERE user_id=1")
    def test_duplicate_identity(self):
        self.assertFalse(media_available(self.db,2,'stable','new-id',None))
    def test_own_media(self):
        self.assertTrue(media_available(self.db,1,'stable','old-photo',None))
    def test_legacy_file(self):
        self.assertFalse(media_available(self.db,2,None,'old-photo',None))
    def test_distinct_media(self):
        self.assertTrue(media_available(self.db,2,'different','new-id',None))
    def test_unique_constraint(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO profiles VALUES(2,'other',NULL,'stable')")
    def test_deleted_profile(self):
        self.db.execute('DELETE FROM profiles WHERE user_id=1')
        self.assertTrue(media_available(self.db,2,'stable','old-photo',None))
    def test_identity_validation(self):
        self.assertEqual(media_identity(SimpleNamespace(file_unique_id='abc')),'abc')
        self.assertIsNone(media_identity(SimpleNamespace(file_unique_id=123)))
