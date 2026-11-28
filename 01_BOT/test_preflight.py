import unittest
import base64
from lumi_preflight import validate

class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.env = {'BOT_TOKEN':'12345:'+'a'*35, 'LUMI_BACKUP_KEY':base64.urlsafe_b64encode(bytes(range(32))).decode()}
    def reject(self, name, value):
        self.env[name] = value
        with self.assertRaises(RuntimeError) as err:
            validate(env=self.env)
        self.assertIn(name, str(err.exception))
        if len(value)>12: self.assertNotIn(value, str(err.exception))
    def test_valid(self): validate(env=self.env)
    def test_missing_key(self): self.reject('LUMI_BACKUP_KEY','')
    def test_invalid_key(self): self.reject('LUMI_BACKUP_KEY','private-invalid-secret')
    def test_disable_backup(self): self.reject('LUMI_AUTO_BACKUP','0')
    def test_dev(self): validate(env={**self.env,'LUMI_ENV':'development','LUMI_AUTO_BACKUP':'0','LUMI_BACKUP_KEY':''})
    def test_bad_token(self): self.reject('BOT_TOKEN','private-invalid-secret')
    def test_bad_url(self): self.reject('LUMI_GAMES_URL','https://user:password@example.com')
    def test_missing_sync(self):
        self.env['LUMI_GAMES_URL']='https://example.com'
        self.reject('LUMI_BAN_SYNC_KEY','')
    def test_valid_sync(self): validate(env={**self.env,'LUMI_GAMES_URL':'https://example.com','LUMI_BAN_SYNC_KEY':'abcdefgh0123456789'*3})
    def test_bad_limit(self): self.reject('LUMI_POLLING_LIMIT','999')
    def test_same_bot(self): self.reject('LUMI_ADMIN_BOT_TOKEN','12345:'+'b'*35)
    def test_admin(self): validate('admin',{**self.env,'LUMI_ADMIN_BOT_TOKEN':'23456:'+'b'*35,'LUMI_ADMIN_IDS':'1, 2'})
    def test_admin_bad_ids(self): self.reject('LUMI_ADMIN_IDS','123,bad')
