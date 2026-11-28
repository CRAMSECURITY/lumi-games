import os
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
from lumi_continuity import assess

class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.now = datetime.now(timezone.utc)
        self.backup = self.directory / self.now.strftime('lumi_%Y-%m-%d.db.enc')
    def check(self):
        return assess(self.directory, self.directory, b'key', now=self.now)
    def test_missing(self):
        with self.assertRaises(ValueError): self.check()
    def test_fresh(self):
        self.backup.touch(); os.utime(self.backup, (self.now.timestamp()-1,)*2)
        with patch('lumi_continuity.drill') as drill:
            self.assertTrue(self.check()); drill.assert_called_once()
    def test_stale(self):
        self.backup.touch(); os.utime(self.backup, (self.now.timestamp()-200000,)*2)
        with self.assertRaises(ValueError): self.check()
    def test_corrupt(self):
        self.backup.touch(); os.utime(self.backup, (self.now.timestamp()-1,)*2)
        with patch('lumi_continuity.drill', side_effect=ValueError):
            with self.assertRaises(ValueError): self.check()
    def test_future(self):
        self.backup.touch(); os.utime(self.backup, (self.now.timestamp()+100,)*2)
        with self.assertRaises(ValueError): self.check()
if __name__ == '__main__': unittest.main()
