import ast, unittest, asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
source=Path(__file__).with_name('bot.py'); tree=ast.parse(source.read_text())
class Tests(unittest.TestCase):
    def test_state_declared(self):
        self.assertTrue(any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ACTIVE_BROWSE_TARGET' for t in n.targets) for n in tree.body))
    def test_bottom_dispatch(self):
        fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='reaction_from_bottom_bar'); fn.decorator_list=[]
        commit=Mock(return_value={'ok':True,'new_like':False,'mutual':False}); nxt=AsyncMock()
        ns=dict(Message=object,ACTIVE_BROWSE_TARGET={1:(42,100)},commit_profile_reaction=commit,show_next=nxt,ReplyKeyboardRemove=SimpleNamespace)
        exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),ns)
        m=SimpleNamespace(from_user=SimpleNamespace(id=1),message_id=99,text='❤️ Нравится',answer=AsyncMock())
        asyncio.run(ns[fn.name](m)); commit.assert_not_called()
        m.message_id=101; asyncio.run(ns[fn.name](m)); commit.assert_called_once_with(1,42,'like'); nxt.assert_awaited_once_with(m,1); self.assertEqual(ns['ACTIVE_BROWSE_TARGET'],{})
    def test_panel_persistent(self):
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='browse_reply_keyboard'); ns=dict(ReplyKeyboardMarkup=SimpleNamespace,KeyboardButton=SimpleNamespace); exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),ns); self.assertFalse(ns[fn.name]().is_persistent)
