import ast, unittest
from pathlib import Path
from types import SimpleNamespace
p=Path(__file__).with_name('bot.py'); tree=ast.parse(p.read_text(encoding='utf-8'))
class ProfileHub(unittest.TestCase):
    def test_menu(self):
        ns=dict(InlineKeyboardMarkup=SimpleNamespace,InlineKeyboardButton=SimpleNamespace)
        f=next(n for n in tree.body if getattr(n,'name',None)=='mobile_profile_keyboard'); exec(compile(ast.Module(body=[f],type_ignores=[]),str(p),'exec'),ns)
        self.assertEqual([b.callback_data for r in ns[f.name]().inline_keyboard for b in r],['ux:edit_photo','ux:edit_text','ux:privacy','ux:home'])
    def test_back(self):
        ns=dict(InlineKeyboardMarkup=SimpleNamespace,InlineKeyboardButton=SimpleNamespace)
        f=next(n for n in tree.body if getattr(n,'name',None)=='profile_back_keyboard'); exec(compile(ast.Module(body=[f],type_ignores=[]),str(p),'exec'),ns)
        self.assertEqual(ns[f.name]().inline_keyboard[0][0].callback_data,'ux:profile')
    def test_no_old_prompt(self):
        self.assertNotIn('Выбери реакцию внизу',p.read_text(encoding='utf-8'))
