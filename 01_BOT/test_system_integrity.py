import ast
import unittest
from pathlib import Path
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

class NotificationMenuTests(unittest.IsolatedAsyncioTestCase):
    async def test_callback_acknowledged_and_menu_sent(self):
        tree = ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
        fn = next(n for n in tree.body if getattr(n, 'name', None) == 'notifications_menu')
        fn.decorator_list = []
        class Callback:
            from_user = SimpleNamespace(id=1)
            message = object()
            answer = AsyncMock()
        db = Mock()
        db.execute.return_value.fetchone.side_effect = [(1, 1, 0), (1,)]
        async def send(message, text, **kwargs):
            self.assertIs(message, Callback.message)
            self.assertIn('Уведомления LUMI', text)
        clean = AsyncMock(side_effect=send)
        ns = dict(CallbackQuery=Callback, connect_db=lambda: nullcontext(db), init_ops=Mock(), InlineKeyboardMarkup=lambda **kw: kw, InlineKeyboardButton=lambda **kw: kw, clean_answer=clean)
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'bot.py', 'exec'), ns)
        await ns['notifications_menu'](Callback())
        Callback.answer.assert_awaited_once_with()
        clean.assert_awaited_once()
