import sqlite3, unittest
from lumi_shop_live import init, act

class ShopLive(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:'); self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE profiles(user_id INTEGER PRIMARY KEY, age INTEGER); CREATE TABLE account_suspensions(user_id INTEGER, expires_at TEXT); INSERT INTO profiles VALUES(1,25),(2,25);')
        init(self.db); self.db.commit()
    def test_purchase(self):
        a=act(self.db,1); self.assertEqual(a[0],300)
        self.assertEqual(act(self.db,1,'aurora_frame',a[1])[0],200)
        self.assertEqual(act(self.db,1,'aurora_frame',a[1])[3],'owned')
        self.assertEqual(act(self.db,1)[0],200)
    def test_isolation(self):
        a=act(self.db,1); act(self.db,2)
        self.assertIsNone(act(self.db,2,'aurora_frame',a[1])); self.assertEqual(act(self.db,2)[2],[])
    def test_delete(self):
        a=act(self.db,1); act(self.db,1,'aurora_frame',a[1]); self.db.execute('DELETE FROM profiles WHERE user_id=1'); self.db.commit()
        self.assertEqual(self.db.execute('SELECT count(*) FROM lumi_shop_items').fetchone()[0],0)
        self.db.execute('INSERT INTO profiles VALUES(1,25)'); self.db.commit(); b=act(self.db,1)
        self.assertIsNone(act(self.db,1,'aurora_frame',a[1])); self.assertEqual(b[0],300)
    def test_blocked(self):
        a=act(self.db,1); self.db.execute('INSERT INTO account_suspensions VALUES(1,NULL)'); self.db.commit()
        self.assertIsNone(act(self.db,1,'aurora_frame',a[1])); self.assertIsNone(act(self.db,1))
    def test_unknown(self): self.assertIsNone(act(self.db,99))
    def test_insufficient(self):
        a=act(self.db,1); act(self.db,1,'aurora_frame',a[1]); act(self.db,1,'obsidian_glow',a[1]); self.assertEqual(act(self.db,1,'violet_badge',a[1])[3],'insufficient')

class EquipTests(unittest.TestCase):
    setUp = ShopLive.setUp
    def test_equip_owned_only(self):
        from lumi_shop_live import equip, equipped
        a=act(self.db,1)
        self.assertFalse(equip(self.db,1,'aurora_frame',a[1]))
        act(self.db,1,'aurora_frame',a[1])
        self.assertTrue(equip(self.db,1,'aurora_frame',a[1]))
        self.assertEqual(equipped(self.db,1),'aurora_frame')
        self.assertTrue(equip(self.db,1,None,a[1]))
        self.assertIsNone(equipped(self.db,1))
    def test_equip_isolation_and_delete(self):
        from lumi_shop_live import equip, equipped
        a=act(self.db,1); b=act(self.db,2)
        act(self.db,1,'aurora_frame',a[1]); equip(self.db,1,'aurora_frame',a[1])
        self.assertFalse(equip(self.db,2,'aurora_frame',a[1]))
        self.assertFalse(equip(self.db,2,'aurora_frame',b[1]))
        self.db.execute('DELETE FROM profiles WHERE user_id=1'); self.db.commit()
        self.assertIsNone(equipped(self.db,1))
        self.assertEqual(self.db.execute('SELECT count(*) FROM lumi_shop_equipped').fetchone()[0],0)
        self.db.execute('INSERT INTO profiles VALUES(1,25)'); self.db.commit(); act(self.db,1)
        self.assertFalse(equip(self.db,1,None,a[1]))
    def test_equip_blocked(self):
        from lumi_shop_live import equip, equipped
        a=act(self.db,1); act(self.db,1,'aurora_frame',a[1]); equip(self.db,1,'aurora_frame',a[1])
        self.db.execute('INSERT INTO account_suspensions VALUES(1,NULL)'); self.db.commit()
        self.assertIsNone(equipped(self.db,1)); self.assertFalse(equip(self.db,1,None,a[1]))
