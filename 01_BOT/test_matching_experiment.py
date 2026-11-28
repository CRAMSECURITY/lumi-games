import unittest
from lumi_matching import score

class MatchingTests(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(score('Berlin','music travel','BERLIN','travel music'),100)
    def test_empty(self):
        self.assertEqual(score('', '', '', ''),0)
    def test_unrelated(self):
        self.assertEqual(score('Berlin','music','Paris','sport'),0)
    def test_overlap(self):
        self.assertGreater(score('','music travel','','music travel'),score('','music travel','','music sport'))
    def test_repetition(self):
        self.assertEqual(score('','music','','music music music'),60)
    def test_unicode(self):
        self.assertEqual(score('  МОСКВА ','Музыка','москва','музыка'),100)
    def test_bounds(self):
        self.assertLessEqual(score('x','music '*10000,'x','music '*10000),100)

if __name__ == '__main__': unittest.main()
