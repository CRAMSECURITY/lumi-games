"""Fail-closed dependency audit; no deployment or package installation."""
import argparse
import base64
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]

def lock_errors(manifest, lock):
    errors = []
    packages = lock.get('packages', {})
    if lock.get('lockfileVersion') != 3 or not packages:
        errors.append('Expected npm lockfile v3 with packages')
    root = packages.get('', {})
    for key in ('dependencies', 'devDependencies', 'optionalDependencies'):
        if manifest.get(key, {}) != root.get(key, {}):
            errors.append(f'Manifest/lock mismatch: {key}')
    for name, entry in packages.items():
        if not name:
            continue
        try:
            url = urlsplit(entry.get('resolved', ''))
            if (url.scheme != 'https' or url.netloc != 'registry.npmjs.org' or
                    not url.path.endswith('.tgz') or url.query or url.fragment):
                raise ValueError('unexpected registry')
            algorithm, digest = entry.get('integrity', '').split('-', 1)
            if algorithm != 'sha512' or len(base64.b64decode(digest, validate=True)) != 64:
                raise ValueError('invalid SHA-512 integrity')
            if not entry.get('version') or entry.get('hasInstallScript') not in (None, True, False):
                raise ValueError('invalid package metadata')
        except (ValueError, TypeError) as exc:
            errors.append(f'{name}: {exc}')
    return errors

def audit(command, cwd):
    try:
        result = subprocess.run(command, cwd=cwd, timeout=180, check=False)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f'Audit unavailable: {exc}', file=sys.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Only inspect npm lock metadata; not a CVE audit')
    args = parser.parse_args()
    app = ROOT / '02_MINI_APP'
    manifest = json.loads((app / 'package.json').read_text(encoding='utf-8'))
    lock = json.loads((app / 'package-lock.json').read_text(encoding='utf-8'))
    errors = lock_errors(manifest, lock)
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f'NPM lock metadata OK: {len(lock["packages"])-1} packages', flush=True)
    if args.offline:
        print('OFFLINE ONLY: CVE audit not performed; release not approved.')
        return 0
    npm = shutil.which('npm')
    npm_ok = bool(npm) and audit([npm, 'audit', '--audit-level=low', '--registry=https://registry.npmjs.org'], app)
    py_ok = audit([sys.executable, '-m', 'pip_audit', '-r', str(ROOT / '01_BOT' / 'requirements.txt'), '--strict'], ROOT)
    if not (npm_ok and py_ok):
        print('RELEASE BLOCKED: vulnerabilities or incomplete dependency audit.', file=sys.stderr)
        return 1
    print('Dependency scans passed for resolved inputs; other release checks still required.')
    return 0

if __name__ == '__main__':
    sys.exit(main())
