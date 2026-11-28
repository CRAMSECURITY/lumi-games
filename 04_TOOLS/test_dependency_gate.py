import copy
import json
import unittest
from dependency_gate import ROOT, lock_errors

class DependencyGateTests(unittest.TestCase):
    def setUp(self):
        app = ROOT / '02_MINI_APP'
        self.manifest = json.loads((app / 'package.json').read_text())
        self.lock = json.loads((app / 'package-lock.json').read_text())
        self.entry = next(v for k,v in self.lock['packages'].items() if k)
    def test_original(self):
        self.assertEqual(lock_errors(self.manifest, self.lock), [])
    def test_registry(self):
        self.entry['resolved'] = 'https://registry.npmjs.org.evil.invalid/a.tgz'
        self.assertTrue(lock_errors(self.manifest, self.lock))
    def test_insecure_transport(self):
        self.entry['resolved'] = self.entry['resolved'].replace('https:', 'http:')
        self.assertTrue(lock_errors(self.manifest, self.lock))
    def test_integrity(self):
        self.entry['integrity'] = 'sha512-YQ=='
        self.assertTrue(lock_errors(self.manifest, self.lock))
    def test_manifest(self):
        self.manifest['dependencies'] = {'unexpected': '1.0.0'}
        self.assertTrue(lock_errors(self.manifest, self.lock))
    def test_missing_integrity(self):
        del self.entry['integrity']
        self.assertTrue(lock_errors(self.manifest, self.lock))

if __name__ == '__main__':
    unittest.main()
