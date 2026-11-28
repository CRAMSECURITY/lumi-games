"""Encrypted-only backup policy; prune only after a verified snapshot exists."""
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
import os
import stat
from cryptography.fernet import Fernet
from lumi_backup_crypto import write_encrypted, decrypt_snapshot
from lumi_database_vault import connect_private


def verify_snapshot(path, key):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('Unsafe backup file')
    data = decrypt_snapshot(path.read_bytes(), key)
    with closing(sqlite3.connect(':memory:')) as db:
        db.deserialize(data)
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('Invalid backup database')


def create_daily_backup(db_path, directory, key, retention=7, now=None):
    Fernet(key)  # validate before touching existing copies
    if not 1 <= retention <= 3650:
        raise ValueError('Invalid retention')
    now = now or datetime.now(timezone.utc)
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Unsafe backup directory')
    if os.name == 'posix':
        if directory.stat().st_uid != os.getuid():
            raise ValueError('Backup directory must belong to service user')
        os.chmod(directory, 0o700)
    target = directory / ('lumi_' + now.strftime('%Y-%m-%d') + '.db.enc')
    if not target.exists() and not target.is_symlink():
        with closing(connect_private(db_path)) as source, closing(sqlite3.connect(':memory:')) as destination:
            source.backup(destination)
            if destination.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise ValueError('Invalid source snapshot')
            write_encrypted(target, destination.serialize(), key)
    verify_snapshot(target, key)
    cutoff = now.date() - timedelta(days=retention)
    # Legacy plaintext files are intentionally not silently deleted or converted.
    for old in directory.glob('lumi_????-??-??.db.enc'):
        try:
            day = datetime.strptime(old.name[5:15], '%Y-%m-%d').date()
        except ValueError:
            continue
        if day < cutoff and old.is_file() and not old.is_symlink():
            old.unlink()
    return target
