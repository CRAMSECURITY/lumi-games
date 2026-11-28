import sqlite3, unittest, ast
from pathlib import Path
from lumi_db_performance import install_indexes, moment_candidates

class DatabasePerformance(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:'); self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE profiles(user_id INTEGER PRIMARY KEY, age, city, interests, gender, seeking);
        CREATE TABLE moderation_holds(user_id INTEGER PRIMARY KEY,expires_at);
        CREATE TABLE privacy_settings(user_id INTEGER PRIMARY KEY,discoverable);
        CREATE TABLE blocks(user_id,blocked_id,PRIMARY KEY(user_id,blocked_id));
        CREATE TABLE reactions(from_user,to_user,liked,PRIMARY KEY(from_user,to_user));
        CREATE TABLE profile_views(viewer_id,target_id,PRIMARY KEY(viewer_id,target_id));
        CREATE TABLE browse_daily(user_id,day,PRIMARY KEY(user_id,day));
        CREATE TABLE lumi_starter_daily(from_user,to_user,day,PRIMARY KEY(from_user,to_user,day));
        CREATE TABLE support_tickets(status,updated_at);''')
        self.db.executemany('INSERT INTO profiles VALUES (?,?,?,?,?,?)',[(1,25,'Берлин','','м','ж')]+[(i,25,'БЕРЛИН','','ж','м') for i in range(2,1002)])
        tree=ast.parse(Path(__file__).with_name('bot.py').read_text()); ns={}
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('mystery_eligible','is_discoverable')],type_ignores=[]),'bot.py','exec'),ns)
        self.old=ns['mystery_eligible']
    def test_equivalence_and_query_count(self):
        d=self.db; d.executescript("INSERT INTO blocks VALUES(1,2),(3,1); INSERT INTO reactions VALUES(1,4,1),(1,5,0); INSERT INTO privacy_settings VALUES(6,0); INSERT INTO moderation_holds VALUES(7,NULL),(8,'2000-01-01'); UPDATE profiles SET age=17 WHERE user_id=9; UPDATE profiles SET seeking='ж' WHERE user_id=10; UPDATE profiles SET city='Paris' WHERE user_id=11;")
        traces=[]; d.set_trace_callback(traces.append)
        rows=d.execute('SELECT user_id,age,city,interests,gender,seeking FROM profiles WHERE user_id!=1 AND age>=18 AND age BETWEEN 18 AND 100').fetchall()
        old=[r for r in rows if self.old(d,1,r[0]) and r[2].casefold()=='берлин' and not d.execute('SELECT 1 FROM reactions WHERE from_user=1 AND to_user=? AND liked=1',(r[0],)).fetchone()]; count=len(traces); traces.clear()
        self.assertEqual(old,moment_candidates(d,1,(18,100,'берлин'))); self.assertEqual(len(traces),1); print('SQL statements old/new:',count, len(traces))
        d.execute('INSERT INTO privacy_settings VALUES(1,0)'); self.assertEqual(moment_candidates(d,1,(18,100,'')),[])
    def test_indexes(self):
        d=self.db; queries=['SELECT * FROM profile_views WHERE target_id=5',"SELECT * FROM browse_daily WHERE day<'2020'", "SELECT * FROM lumi_starter_daily WHERE day<'2020'", "SELECT * FROM support_tickets WHERE status='closed' AND updated_at<'2020'"]
        for q in queries: self.assertIn('SCAN',d.execute('EXPLAIN QUERY PLAN '+q).fetchone()[3])
        install_indexes(d); install_indexes(d)
        for q in queries:
            plan=d.execute('EXPLAIN QUERY PLAN '+q).fetchone()[3]; self.assertIn('SEARCH',plan); print(plan)
if __name__=='__main__': unittest.main()
