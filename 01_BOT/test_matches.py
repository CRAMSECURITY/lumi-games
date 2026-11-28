import ast, sqlite3, unittest
from pathlib import Path
from types import SimpleNamespace
source=Path(__file__).with_name('bot.py')
tree=ast.parse(source.read_text(encoding='utf-8'))
names={'record_reaction','is_match','new_match_keyboard'}
ns=dict(InlineKeyboardMarkup=SimpleNamespace,InlineKeyboardButton=SimpleNamespace,game_button=lambda:SimpleNamespace(text='LUMI GAMES'))
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),str(source),'exec'),ns)
class Tests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:'); self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE reactions(from_user INTEGER,to_user INTEGER,liked INTEGER,PRIMARY KEY(from_user,to_user)); CREATE TABLE profiles(user_id INTEGER PRIMARY KEY); INSERT INTO profiles VALUES(1),(2); CREATE TABLE blocks(user_id INTEGER,blocked_id INTEGER);')
    def record(self,a,b,liked): return ns['record_reaction'](self.db,a,b,liked)
    def match(self): return ns['is_match'](self.db,1,2)
    def test_skip_then_like(self):
        self.assertTrue(self.record(1,2,False)); self.assertTrue(self.record(1,2,True)); self.assertEqual(self.db.execute('SELECT liked FROM reactions').fetchone(),(1,))
    def test_duplicate(self):
        self.assertTrue(self.record(1,2,True)); self.assertFalse(self.record(1,2,True))
    def test_no_downgrade(self):
        self.record(1,2,True); self.assertFalse(self.record(1,2,False)); self.assertEqual(self.db.execute('SELECT liked FROM reactions').fetchone(),(1,))
    def test_mutual(self):
        self.record(1,2,False); self.record(2,1,True); self.assertFalse(self.match()); self.record(1,2,True); self.assertTrue(self.match())
    def test_block(self):
        self.record(1,2,True); self.record(2,1,True); self.db.execute('INSERT INTO blocks VALUES(2,1)'); self.assertFalse(self.match())
    def test_deleted(self):
        self.record(1,2,True); self.record(2,1,True); self.db.execute('DELETE FROM profiles WHERE user_id=2'); self.assertFalse(self.match())
    def test_buttons(self):
        buttons=[b for row in ns['new_match_keyboard'](42).inline_keyboard for b in row]; self.assertIn('LUMI GAMES',[b.text for b in buttons]); self.assertTrue({'hello:menu:42','chat:42','games:42','arena:challenge:42','ux:matches'} <= {getattr(b,'callback_data',None) for b in buttons})
if __name__=='__main__': unittest.main(verbosity=2)
