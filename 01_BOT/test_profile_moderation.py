import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from lumi_profile_moderation import profile_text_allowed

class ProfileModerationTests(unittest.TestCase):
    def test_normal(self):
        for value in ('Анна', 'Санкт-Петербург', 'Люблю кино\nи музыку ❤️', '👩‍💻'):
            self.assertTrue(profile_text_allowed(value))
    def test_risks(self):
        for value in ('example.com', 'переведи деньги', 'exam\u200bple.com', 'код из смс'):
            self.assertFalse(profile_text_allowed(value))
    def test_controls(self):
        for value in ('\u200b', 'abc\u202e', 'abc\x00', '   ', None):
            self.assertFalse(profile_text_allowed(value))
    def test_hidden_link(self):
        self.assertFalse(profile_text_allowed('Привет', [SimpleNamespace(type='text_link')]))
    def test_handlers(self):
        tree = ast.parse(Path(__file__).with_name('bot.py').read_text())
        for name in ('get_name','get_city','registration_nickname','get_description','save_new_text'):
            fn = next(n for n in tree.body if getattr(n,'name',None)==name)
            self.assertTrue(any(isinstance(n,ast.Call) and getattr(n.func,'id',None)=='profile_text_allowed' for n in ast.walk(fn)), name)
