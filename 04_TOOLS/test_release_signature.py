import tempfile
import unittest
from pathlib import Path
from cryptography.exceptions import InvalidSignature
import release_signature as s

class SignatureTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.archive, self.private, self.public, self.sig = [self.root / x for x in ('a.zip','private','public','sig')]
        self.archive.write_bytes(b'example archive')
        s.generate(self.private,self.public); s.sign(self.archive,self.private,self.sig)
    def test_valid(self): s.verify(self.archive,self.public,self.sig)
    def test_modified_archive(self):
        self.archive.write_bytes(b'changed')
        with self.assertRaises(InvalidSignature): s.verify(self.archive,self.public,self.sig)
    def test_modified_signature(self):
        data = bytearray(self.sig.read_bytes()); data[0] ^= 1; self.sig.write_bytes(data)
        with self.assertRaises(InvalidSignature): s.verify(self.archive,self.public,self.sig)
    def test_wrong_key(self):
        p = self.root/'p2'; q = self.root/'q2'; s.generate(p,q)
        with self.assertRaises(InvalidSignature): s.verify(self.archive,q,self.sig)
    def test_no_overwrite(self):
        with self.assertRaises(FileExistsError): s.generate(self.private,self.public)
    def test_missing_signature(self):
        self.sig.unlink()
        with self.assertRaises(FileNotFoundError): s.verify(self.archive,self.public,self.sig)
