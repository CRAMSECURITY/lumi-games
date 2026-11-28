import unittest, tempfile
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from lumi_backup_crypto import write_encrypted, decrypt_snapshot
class BackupCryptoTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'backup.enc'; key=Fernet.generate_key(); write_encrypted(p,b'private profile',key)
            self.assertNotIn(b'private profile',p.read_bytes()); self.assertEqual(decrypt_snapshot(p.read_bytes(),key),b'private profile')
            with self.assertRaises(InvalidToken): decrypt_snapshot(p.read_bytes(),Fernet.generate_key())
    def test_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'backup.enc'; key=Fernet.generate_key(); write_encrypted(p,b'data',key)
            data=bytearray(p.read_bytes()); data[20]=65 if data[20]!=65 else 66
            with self.assertRaises(InvalidToken): decrypt_snapshot(bytes(data),key)
