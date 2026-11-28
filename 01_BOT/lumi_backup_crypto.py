"""Authenticated encryption for SQLite backup snapshots; key kept outside archive."""
from cryptography.fernet import Fernet
from pathlib import Path
import os
import tempfile

def encrypt_snapshot(data, key):
    return Fernet(key).encrypt(data)

def decrypt_snapshot(data, key):
    return Fernet(key).decrypt(data)

def write_encrypted(target, data, key):
    payload = encrypt_snapshot(data, key)
    target = Path(target)
    fd, name = tempfile.mkstemp(prefix='.encrypted_', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
