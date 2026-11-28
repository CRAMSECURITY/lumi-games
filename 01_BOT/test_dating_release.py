import ast, sqlite3, unittest, asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from contextlib import nullcontext
p=Path(__file__).with_name('bot.py'); tree=ast.parse(p.read_text(encoding='utf-8'))
class DatingTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:'); self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE active_chats(user_id INTEGER PRIMARY KEY,peer_id INTEGER); INSERT INTO active_chats VALUES(1,2),(2,1); CREATE TABLE game_sessions(user_a INTEGER,user_b INTEGER,game_type TEXT,question_id INTEGER,answer_a INTEGER,answer_b INTEGER,PRIMARY KEY(user_a,user_b));')
        self.ns=dict(connect_db=lambda:nullcontext(self.db),InlineKeyboardMarkup=SimpleNamespace,InlineKeyboardButton=SimpleNamespace,CallbackQuery=object,Message=object,FSMContext=object,show_matches_page=AsyncMock(),mobile_home=AsyncMock())
        for name in ['close_active_chat','chat_reply_keyboard','chat_controls','reserve_pair_game','stop_chat_button','lumi_navigation']:
            fn=next(n for n in tree.body if getattr(n,'name',None)==name); fn.decorator_list=[]
            exec(compile(ast.Module(body=[fn],type_ignores=[]),str(p),'exec'),self.ns)
    def test_close_only_own(self):
        self.ns['close_active_chat'](1); self.assertEqual(self.db.execute('SELECT * FROM active_chats').fetchall(),[(2,1)])
    def test_duplicate_invite_preserves_answer(self):
        f=self.ns['reserve_pair_game']; self.assertTrue(f(self.db,1,2,3)); self.db.execute('UPDATE game_sessions SET answer_a=1'); self.assertFalse(f(self.db,1,2,4)); self.assertEqual(self.db.execute('SELECT question_id,answer_a FROM game_sessions').fetchone(),(3,1))
    def test_reply_target(self):
        kb=self.ns['chat_reply_keyboard'](42); self.assertEqual(kb.inline_keyboard[0][0].callback_data,'chat:42'); self.assertEqual(kb.inline_keyboard[1][1].callback_data,'blockmatch:42')
    def test_stop_button(self):
        c=SimpleNamespace(from_user=SimpleNamespace(id=1),answer=AsyncMock(),message=object()); asyncio.run(self.ns['stop_chat_button'](c)); self.assertIsNone(self.db.execute('SELECT 1 FROM active_chats WHERE user_id=1').fetchone()); self.ns['show_matches_page'].assert_awaited_once_with(c.message,1)
    def test_home_closes_chat(self):
        m=SimpleNamespace(from_user=SimpleNamespace(id=1),text='/home'); st=SimpleNamespace(clear=AsyncMock()); asyncio.run(self.ns['lumi_navigation'](m,st)); self.assertIsNone(self.db.execute('SELECT 1 FROM active_chats WHERE user_id=1').fetchone()); st.clear.assert_awaited_once(); self.ns['mobile_home'].assert_awaited_once_with(m)
    def test_chat_controls(self):
        self.assertEqual(self.ns['chat_controls']().inline_keyboard[0][0].callback_data,'chatstop:now')
    def test_media_reply_markup(self):
        f=next(n for n in tree.body if getattr(n,'name',None)=='fallback'); calls=[n for n in ast.walk(f) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('send_message','send_photo','send_voice')]; self.assertEqual(len(calls),3); self.assertTrue(all(any(k.arg=='reply_markup' and isinstance(k.value,ast.Call) and getattr(k.value.func,'id','')=='chat_reply_keyboard' for k in c.keywords) for c in calls))
