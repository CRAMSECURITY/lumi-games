import io
import logging
import unittest
from unittest.mock import patch
from urllib.parse import quote
from lumi_secrets import redact, SecretFormatter, install_log_redaction


class SecretsTests(unittest.TestCase):
    def test_configured_secrets(self):
        for name in ('BOT_TOKEN','LUMI_ADMIN_BOT_TOKEN','LUMI_BACKUP_KEY','LUMI_BAN_SYNC_KEY'):
            secret = 'private-example+/=12345678'
            self.assertEqual(redact(secret, {name: secret}), '[REDACTED]')
            self.assertEqual(redact(quote(secret, safe=''), {name: secret}), '[REDACTED]')

    def test_unknown_telegram_token(self):
        token = '123456789:' + 'A'*35
        self.assertNotIn(token, redact('https://api.telegram.org/bot'+token+'/getMe', {}))
        self.assertNotIn(quote(token, safe=''), redact(quote(token, safe=''), {}))

    def test_exception_and_arguments(self):
        secret = 'a-secret-for-testing-123456'
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        handler.setFormatter(SecretFormatter(logging.Formatter('%(levelname)s %(message)s')))
        logger = logging.Logger('test'); logger.addHandler(handler)
        with patch.dict('os.environ', {'LUMI_BAN_SYNC_KEY':secret}):
            try:
                raise ValueError(secret)
            except ValueError:
                logger.exception('failed %s', secret)
        self.assertNotIn(secret, output.getvalue())
        self.assertIn('Traceback', output.getvalue())
        self.assertIn('[REDACTED]', output.getvalue())

    def test_install_idempotent(self):
        root = logging.getLogger(); handler = logging.StreamHandler(); root.addHandler(handler)
        try:
            install_log_redaction(); first = handler.formatter
            install_log_redaction(); self.assertIs(handler.formatter, first)
        finally:
            root.removeHandler(handler)

    def test_normal_text(self):
        self.assertEqual(redact('normal error 42', {}), 'normal error 42')
