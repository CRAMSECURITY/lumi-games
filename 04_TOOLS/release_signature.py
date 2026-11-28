"""Detached Ed25519 signatures for ZIP releases; keep verifier and trusted key outside ZIP."""
import argparse
import hashlib
import os
import sys
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

DOMAIN = b'LUMI-ZIP-SHA256-v1\x00'

def message(path):
    with Path(path).open('rb') as f:
        h = hashlib.sha256()
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return DOMAIN + h.digest()

def exclusive(path, data, mode=0o600):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode), 'wb') as f:
        f.write(data)

def generate(private, public):
    key = Ed25519PrivateKey.generate()
    exclusive(private, key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()))
    exclusive(public, key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw), 0o644)

def sign(archive, private, signature):
    key = Ed25519PrivateKey.from_private_bytes(Path(private).read_bytes())
    exclusive(signature, key.sign(message(archive)), 0o644)

def verify(archive, public, signature):
    key = Ed25519PublicKey.from_public_bytes(Path(public).read_bytes())
    key.verify(Path(signature).read_bytes(), message(archive))

def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    for name, args in [('generate', ('private','public')), ('sign', ('archive','private','signature')), ('verify', ('archive','public','signature'))]:
        s = sub.add_parser(name)
        for arg in args: s.add_argument(arg)
    a = vars(p.parse_args()); action = a.pop('action')
    try:
        {'generate':generate,'sign':sign,'verify':verify}[action](**a)
    except (OSError, ValueError, InvalidSignature):
        print('FAILED: invalid signature, key or file', file=sys.stderr); return 1
    print('OK:', action); return 0

if __name__ == '__main__': sys.exit(main())
