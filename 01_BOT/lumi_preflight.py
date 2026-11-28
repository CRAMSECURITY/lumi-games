"""Validate deployment settings before touching SQLite or Telegram; never echo values."""
import os
import re
import base64
import binascii
from urllib.parse import urlsplit


def validate(role='bot', env=None):
    env = os.environ if env is None else env
    errors = []
    def get(name, default=''):
        return env.get(name, default)
    def integer(name, default, low, high):
        value = get(name, str(default))
        if not re.fullmatch(r'[0-9]{1,6}', value) or not low <= int(value) <= high:
            errors.append(f'{name}: integer {low}..{high} required')
    mode = get('LUMI_ENV', 'production')
    if mode not in ('production', 'development'):
        errors.append('LUMI_ENV: production or development required')
    production = mode != 'development'
    main = get('BOT_TOKEN')
    admin = get('LUMI_ADMIN_BOT_TOKEN')
    def token_ok(value):
        return bool(re.fullmatch(r'[1-9][0-9]{0,19}:[A-Za-z0-9_-]{20,128}', value))
    if not token_ok(main):
        errors.append('BOT_TOKEN: invalid or missing Telegram token')
    if role == 'admin' or admin:
        if not token_ok(admin):
            errors.append('LUMI_ADMIN_BOT_TOKEN: invalid or missing Telegram token')
        if admin and main and admin.split(':', 1)[0] == main.split(':', 1)[0]:
            errors.append('LUMI_ADMIN_BOT_TOKEN: separate bot identity required')
    ids = get('LUMI_ADMIN_IDS').replace(' ', '')
    if (role == 'admin' or admin or ids) and (not ids or any(not re.fullmatch(r'[1-9][0-9]{0,15}', x) or int(x) >= 2**53 for x in ids.split(','))):
        errors.append('LUMI_ADMIN_IDS: positive Telegram IDs required')
    if role == 'bot':
        backup = get('LUMI_AUTO_BACKUP', '1')
        if backup not in ('0', '1') or (production and backup != '1'):
            errors.append('LUMI_AUTO_BACKUP: encrypted backups required in production')
        if backup != '0':
            key = get('LUMI_BACKUP_KEY').strip()
            try:
                decoded = base64.b64decode(key, altchars=b'-_', validate=True)
                valid = len(decoded) == 32 and base64.urlsafe_b64encode(decoded).decode() == key
            except (ValueError, binascii.Error):
                valid = False
            if not valid:
                errors.append('LUMI_BACKUP_KEY: valid Fernet key required')
        integer('LUMI_BACKUP_RETENTION_DAYS', 7, 1, 3650)
        integer('LUMI_POLLING_LIMIT', 32, 1, 256)
        integer('LUMI_DAILY_PROFILE_LIMIT', 80, 10, 500)
        integer('LUMI_AUDIT_RETENTION_DAYS', 30, 7, 365)
        url = get('LUMI_GAMES_URL').strip()
        if url:
            try:
                p = urlsplit(url)
                valid = (p.scheme == 'https' and bool(p.hostname) and not p.username and not p.password
                         and not p.fragment and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url)
                         and '\\' not in url and (p.port is None or 1 <= p.port <= 65535))
            except ValueError:
                valid = False
            if not valid:
                errors.append('LUMI_GAMES_URL: valid HTTPS URL without credentials or fragment required')
            secret = get('LUMI_BAN_SYNC_KEY').strip()
            if (production or secret) and (len(secret) < 32 or len(set(secret)) < 8 or secret in (main, admin, get('LUMI_BACKUP_KEY').strip())):
                errors.append('LUMI_BAN_SYNC_KEY: separate strong secret required')
    elif role == 'admin':
        integer('LUMI_ADMIN_POLLING_LIMIT', 8, 1, 256)
    else:
        errors.append('Unknown role')
    if errors:
        raise RuntimeError('LUMI preflight failed:\n' + '\n'.join(errors))


if __name__ == '__main__':
    import argparse
    from dotenv import load_dotenv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=['bot', 'admin'], default='bot')
    args = parser.parse_args()
    load_dotenv()
    try:
        validate(args.role)
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1)
    print('LUMI preflight OK (local settings only)')
