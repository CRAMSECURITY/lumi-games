import unittest
from lumi_locale import strings, language, RU, EN
from lumi_clubs import CLUBS, ACTIVITIES

class LocaleTests(unittest.TestCase):
    def test_english_variants(self):
        for code in ('en','EN-US','en_GB'):
            self.assertIs(strings(code), EN)
    def test_fallback(self):
        for code in (None, '', 'de', 'ru-RU', 1, 'enough', 'en-'+'x'*40):
            self.assertIs(strings(code), RU)
    def test_complete(self):
        self.assertEqual(set(RU), set(EN))
        self.assertTrue(all(EN.values()))
    def test_preserve_russian(self):
        for key in CLUBS:
            self.assertEqual(RU[key], CLUBS[key])
            self.assertEqual(RU['task_'+key], ACTIVITIES[key])
    def test_immutable(self):
        with self.assertRaises(TypeError):
            EN['title']='changed'
