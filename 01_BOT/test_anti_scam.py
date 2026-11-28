import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from lumi_anti_scam import warning_for

class ScamTests(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(warning_for('Привет! Как дела?'), '')
    def test_links(self):
        for text in ('https://example.com', 'example.ru', 'www.example.org', 'ｈｔｔｐｓ://example.com', 'exam\u200bple.com'):
            with self.subTest(text=text): self.assertTrue(warning_for(text))
    def test_entities(self):
        self.assertTrue(warning_for('нажми', [SimpleNamespace(type='text_link')]))
    def test_risk(self):
        for text in ('Пришли код из смс', 'переведи деньги', 'seed phrase', 'предоплата'):
            self.assertTrue(warning_for(text))
    def test_delivery_budget(self):
        self.assertLess(len('Фото через LUMI\n'+'x'*800+warning_for('example.com')),1024)
        self.assertLess(len('💬 Сообщение через LUMI:\n'+'x'*3800+warning_for('example.com')),4096)
    def test_preview_disabled(self):
        tree=ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
        fn=next(n for n in tree.body if getattr(n,'name',None)=='fallback')
        call=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and getattr(n.func,'attr',None)=='send_message')
        self.assertTrue(any(k.arg=='disable_web_page_preview' and k.value.value is True for k in call.keywords))
