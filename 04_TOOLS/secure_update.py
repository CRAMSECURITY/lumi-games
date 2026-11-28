"""Offline staging only. Run a trusted copy outside the incoming archive."""
import argparse
import hashlib
import json
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path
from release_signature import verify


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{3}\.[0-9]{1,3}', value):
        raise ValueError('Invalid release version')
    return tuple(map(int, value.split('.')))


def stage(archive, public, signature, current, destination):
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('Destination already exists')
    if not destination.parent.is_dir():
        raise ValueError('Destination parent must exist')
    floor = version(current)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.lumi-stage-') as tmp:
        tmp = Path(tmp)
        snapshot = tmp / 'release.zip'
        shutil.copyfile(archive, snapshot)
        verify(snapshot, public, signature)
        root = tmp / 'payload'
        root.mkdir()
        with zipfile.ZipFile(snapshot) as z:
            entries = z.infolist()
            if len(entries) > 5000 or sum(i.file_size for i in entries) > 256 * 1024**2:
                raise ValueError('Archive exceeds staging limits')
            names = set()
            top = set()
            for i in entries:
                name = i.filename.rstrip('/')
                parts = name.split('/')
                if any(not p or p in ('.','..') or p.endswith(('.', ' ')) or any(c in p for c in '\\:<>|?*"') or any(ord(c)<32 for c in p) or p.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{x}' for x in range(1,10)),*(f'LPT{x}' for x in range(1,10))} for p in parts):
                    raise ValueError('Unsafe archive path')
                folded = name.casefold()
                if folded in names:
                    raise ValueError('Duplicate archive path')
                names.add(folded); top.add(parts[0])
                mode = stat.S_IFMT(i.external_attr >> 16)
                if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ValueError('Unsupported archive member')
            if len(top) != 1:
                raise ValueError('Expected one release root')
            for i in entries:
                p = root.joinpath(*i.filename.rstrip('/').split('/'))
                if i.is_dir(): p.mkdir(parents=True, exist_ok=True)
                else:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(i) as src, p.open('xb') as dst: shutil.copyfileobj(src,dst)
        payload = root / next(iter(top))
        metadata = json.loads((payload/'RELEASE_VERSION.json').read_text(encoding='utf-8'))
        if version(metadata['version']) <= floor:
            raise ValueError('Release is not newer than trusted installed version')
        expected = json.loads((payload/'RELEASE_MANIFEST.json').read_text(encoding='utf-8'))
        actual = {p.relative_to(payload).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in payload.rglob('*') if p.is_file() and p != payload/'RELEASE_MANIFEST.json'}
        if not expected or actual != expected:
            raise ValueError('Release inventory mismatch')
        # Reserve destination exclusively; never replace an existing installation.
        destination.mkdir()
        try:
            for p in payload.iterdir(): shutil.move(str(p), destination / p.name)
        except BaseException:
            shutil.rmtree(destination)
            raise
    return metadata['version']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('archive','public','signature','current','destination'): p.add_argument(arg)
    try:
        print('Staged:', stage(**vars(p.parse_args())))
    except Exception:
        p.exit(1, 'Staging failed; do not activate the incoming release.\n')

if __name__ == '__main__': main()
