"""Redact configured secrets and Telegram token patterns from standard log output."""
import logging
import os
import re
from urllib.parse import quote, quote_plus

_SECRET_NAMES = ('BOT_TOKEN', 'LUMI_ADMIN_BOT_TOKEN', 'LUMI_BACKUP_KEY', 'LUMI_BAN_SYNC_KEY')
_TELEGRAM = re.compile(r'(?<![0-9])[0-9]{1,20}(?::|%3[Aa])[A-Za-z0-9_-]{20,128}')


def redact(text, env=None):
    env = os.environ if env is None else env
    variants = set()
    for name in _SECRET_NAMES:
        value = env.get(name, '').strip()
        if len(value) >= 8:
            variants.update((value, quote(value, safe=''), quote_plus(value, safe='')))
    for value in sorted(variants, key=len, reverse=True):
        text = text.replace(value, '[REDACTED]')
    return _TELEGRAM.sub('[REDACTED]', text)


class SecretFormatter(logging.Formatter):
    def __init__(self, original=None):
        super().__init__()
        self.original = original or logging.Formatter()

    def format(self, record):
        # Redact after formatting, including exception messages and traceback.
        return redact(self.original.format(record))


def install_log_redaction():
    for handler in logging.getLogger().handlers:
        if not isinstance(handler.formatter, SecretFormatter):
            handler.setFormatter(SecretFormatter(handler.formatter))
