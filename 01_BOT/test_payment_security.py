import ast, sqlite3, time, unittest
from pathlib import Path
from types import SimpleNamespace

class PaymentTests(unittest.TestCase):
    def setUp(self):
        tree=ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
        names={'premium_accept_payment','premium_apply_refund','premium_expires_at'}
        self.ns={'time':time,'PREMIUM_STARS':199,'PREMIUM_SECONDS':2592000}
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'bot.py','exec'),self.ns)
        self.db=sqlite3.connect(':memory:'); self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE premium_orders(payload TEXT PRIMARY KEY,user_id INTEGER,price INTEGER,status TEXT,created_at INTEGER);
        CREATE TABLE premium_payments(charge_id TEXT PRIMARY KEY,payload TEXT UNIQUE,user_id INTEGER,stars INTEGER,paid_at INTEGER,refunded INTEGER DEFAULT 0);
        CREATE TABLE premium_subscriptions(user_id INTEGER PRIMARY KEY,expires_at INTEGER);
        INSERT INTO premium_orders VALUES('p',1,199,'pending',0);''')
        self.receipt=SimpleNamespace(currency='XTR',total_amount=199,invoice_payload='p',telegram_payment_charge_id='c')
    def pay(self,uid=1):return self.ns['premium_accept_payment'](self.db,uid,self.receipt)
    def refund(self,uid=1):return self.ns['premium_apply_refund'](self.db,uid,self.receipt)
    def test_duplicate_payment(self):
        self.assertTrue(self.pay()); expiry=self.ns['premium_expires_at'](self.db,1)
        self.assertFalse(self.pay()); self.assertEqual(expiry,self.ns['premium_expires_at'](self.db,1))
    def test_wrong_owner(self):self.assertFalse(self.pay(2))
    def test_empty_charge(self):
        self.receipt.telegram_payment_charge_id=''; self.assertFalse(self.pay())
    def test_refund_validation(self):
        self.assertTrue(self.pay()); self.assertFalse(self.refund(2))
        for field,bad in [('currency','USD'),('total_amount',1),('invoice_payload','other')]:
            old=getattr(self.receipt,field);setattr(self.receipt,field,bad);self.assertFalse(self.refund());setattr(self.receipt,field,old)
        self.assertTrue(self.refund());self.assertFalse(self.refund());self.assertEqual(self.ns['premium_expires_at'](self.db,1),0)
    def test_refund_does_not_restore_deleted_subscription(self):
        self.assertTrue(self.pay()); self.db.execute("INSERT INTO premium_orders VALUES('p2',1,199,'pending',0)")
        self.receipt.invoice_payload='p2'; self.receipt.telegram_payment_charge_id='c2'; self.assertTrue(self.pay())
        self.db.execute('DELETE FROM premium_subscriptions');self.assertTrue(self.refund());self.assertEqual(self.ns['premium_expires_at'](self.db,1),0)
