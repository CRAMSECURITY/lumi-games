import json
import tempfile
import unittest
from pathlib import Path
import master_quality as q

class MasterQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.file = self.root / 'app.js'
        self.file.write_text('const x = 1;')
        (self.root / q.MANIFEST).write_text(json.dumps(q.inventory(self.root)))
    def test_valid(self):
        self.assertEqual(q.verify(self.root), 1)
    def test_changed(self):
        self.file.write_text('changed')
        with self.assertRaises(ValueError): q.verify(self.root)
    def test_missing(self):
        self.file.unlink()
        with self.assertRaises(ValueError): q.verify(self.root)
    def test_extra(self):
        (self.root / 'extra.js').touch()
        with self.assertRaises(ValueError): q.verify(self.root)
    def test_private(self):
        (self.root / '.env').touch()
        with self.assertRaises(ValueError): q.inventory(self.root)
    def test_cache_ignored(self):
        (self.root / '__pycache__').mkdir()
        (self.root / '__pycache__' / 'a.pyc').touch()
        self.assertEqual(q.verify(self.root), 1)
