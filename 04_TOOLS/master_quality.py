"""Verify shipped source/assets against a release inventory and check JS syntax."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'RELEASE_MANIFEST.json'
SKIP = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.wrangler', '.pytest_cache'}

def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        if any(part in SKIP for part in rel.parts) or str(rel) == MANIFEST:
            continue
        if path.is_symlink():
            raise ValueError(f'Symbolic link: {rel}')
        if not path.is_file():
            continue
        if path.name.startswith('.env') and path.name not in {'.env.example', '.env.sample'}:
            raise ValueError(f'Private configuration in distribution: {rel}')
        if path.suffix.lower() in {'.db', '.sqlite', '.sqlite3', '.pem', '.key', '.pyc', '.lumi-private'} or path.name.endswith(('-wal', '-shm')):
            raise ValueError(f'Private or generated file in distribution: {rel}')
        result[rel.as_posix()] = digest(path)
    return result

def digest(path):
    with path.open('rb') as stream:
        h = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
        return h.hexdigest()

def verify(root):
    expected = json.loads((root / MANIFEST).read_text(encoding='utf-8'))
    actual = inventory(root)
    if not isinstance(expected, dict) or not expected or actual != expected:
        changed = sorted(k for k in actual.keys() | expected.keys() if actual.get(k) != expected.get(k)) if isinstance(expected, dict) else []
        raise ValueError('Inventory mismatch: ' + ', '.join(changed[:20]))
    return len(actual)

def check_js(root):
    files = [root / name for name in inventory(root) if name.endswith(('.js', '.mjs', '.cjs'))]
    if not files:
        raise ValueError('No JavaScript files found')
    for path in files:
        subprocess.run(['node', '--check', str(path)], cwd=root, check=True, timeout=15)
    return len(files)

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--generate', action='store_true', help='Explicitly regenerate inventory for a clean distribution')
    args = p.parse_args(argv)
    try:
        if args.generate:
            (ROOT / MANIFEST).write_text(json.dumps(inventory(ROOT), indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
        else:
            print(f'Inventory verified: {verify(ROOT)} files')
            print(f'JavaScript syntax verified: {check_js(ROOT)} files')
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f'QUALITY CHECK FAILED: {exc}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
