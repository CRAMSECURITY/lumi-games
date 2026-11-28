import ast, unittest, asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
p=Path(__file__).with_name('bot.py'); tree=ast.parse(p.read_text(encoding='utf-8'))
class Tests(unittest.TestCase):
    def load(self,name,ns):
        fn=next(n for n in tree.body if getattr(n,'name',None)==name); exec(compile(ast.Module(body=[fn],type_ignores=[]),str(p),'exec'),ns); return ns[name]
    def test_keyboard(self):
        kb=self.load('browse_reply_keyboard',dict(ReplyKeyboardMarkup=SimpleNamespace,KeyboardButton=SimpleNamespace))()
        self.assertFalse(kb.is_persistent); self.assertFalse(getattr(kb,"one_time_keyboard",False)); self.assertTrue(kb.resize_keyboard)
    def test_navigation(self):
        kb=self.load('browse_navigation_keyboard',dict(InlineKeyboardMarkup=SimpleNamespace,InlineKeyboardButton=SimpleNamespace))(42)
        self.assertEqual([b.callback_data for b in kb.inline_keyboard[0]],['browse:more:42','ux:home'])
    def test_keep_keyboard_on_success(self):
        active={1:(2,10)}
        async def show(m,u): active[u]=(3,20)
        fn=self.load('show_next',dict(ACTIVE_BROWSE_TARGET=active,_show_next_profile=show,ReplyKeyboardRemove=SimpleNamespace)); m=SimpleNamespace(answer=AsyncMock()); asyncio.run(fn(m,1)); m.answer.assert_not_awaited()
    def test_remove_on_exit(self):
        fn=self.load('show_next',dict(ACTIVE_BROWSE_TARGET={1:(2,10)},_show_next_profile=AsyncMock(),ReplyKeyboardRemove=SimpleNamespace)); m=SimpleNamespace(answer=AsyncMock()); asyncio.run(fn(m,1)); m.answer.assert_awaited_once()
