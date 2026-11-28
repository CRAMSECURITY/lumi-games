import unittest, sqlite3, datetime as dt
from lumi_growth import report
class Growth(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.db.executescript("""CREATE TABLE profiles(user_id INTEGER);
        CREATE TABLE browse_daily(user_id INTEGER,day TEXT,views INTEGER,PRIMARY KEY(user_id,day));
        CREATE TABLE premium_payments(user_id INTEGER,stars INTEGER,paid_at INTEGER,refunded INTEGER);
        INSERT INTO profiles VALUES(1),(2);
        INSERT INTO browse_daily VALUES(1,'2026-11-27',3),(1,'2026-11-28',2),(2,'2026-11-28',1),(3,'2026-11-28',0);
        """)
        self.day=dt.date(2026,11,28)
    def tearDown(self): self.db.close()
    def test_activity(self):
        r=report(self.db,self.day)
        self.assertEqual((r["daily_browsers"],r["seven_day_browsers"],r["next_day_browse_return_rate"]),(2,2,1))
    def test_empty(self):
        self.assertIsNone(report(self.db,dt.date(2026,12,10))["next_day_browse_return_rate"])
    def test_payments(self):
        t=int(dt.datetime(2026,11,28,tzinfo=dt.timezone.utc).timestamp())
        self.db.executemany("INSERT INTO premium_payments VALUES(?,?,?,?)",[(1,10,t,0),(1,20,t,0),(2,99,t,1),(3,99,t-8*86400,0)])
        self.db.commit()
        r=report(self.db,self.day)
        self.assertEqual((r["seven_day_nonrefunded_orders"],r["seven_day_distinct_buyers"],r["seven_day_nonrefunded_stars"]),(2,1,30))
    def test_no_ids(self):
        self.assertNotIn("user_id",report(self.db,self.day))
if __name__=="__main__": unittest.main()
