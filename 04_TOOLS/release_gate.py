"""Run local checks; strict mode also requires installed dependencies and online audits. Never deploys."""
import argparse
import ast
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def run(command, cwd, timeout=300):
    try:
        return subprocess.run(command, cwd=cwd, timeout=timeout, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False

def checks(root, python, node, offline):
    bot, app, tools = (root / p for p in ('01_BOT', '02_MINI_APP', '04_TOOLS'))
    yield 'Distribution integrity and JS syntax', [python, str(tools / 'master_quality.py')], root
    yield 'Python tests', [python, '-m', 'unittest', 'discover', '-p', 'test_*.py'], bot
    yield 'Tool tests', [python, '-m', 'unittest', 'discover', '-p', 'test_*.py'], tools
    yield 'JavaScript tests', [node, '--test', *map(str, sorted((app / 'tests').glob('*.test.js')))], app
    yield 'Dependency audit', [python, str(tools / 'dependency_gate.py'), *(['--offline'] if offline else [])], root
    if not offline:
        yield 'Installed Python dependencies', [python, '-c', 'import aiogram, dotenv, PIL, cryptography'], bot
        yield 'Installed dependency consistency', [python, '-m', 'pip', 'check'], bot

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Local diagnostics only; never approves release')
    args = parser.parse_args(argv)
    node = shutil.which('node') or 'node'
    results = {}
    try:
        for path in ROOT.rglob('*.py'):
            if not any(p in {'.venv', 'venv', 'node_modules', '.git'} for p in path.relative_to(ROOT).parts):
                ast.parse(path.read_bytes(), filename=str(path))
        results['Python syntax'] = True
    except (SyntaxError, OSError, ValueError):
        results['Python syntax'] = False
    for name, command, cwd in checks(ROOT, sys.executable, node, args.offline):
        print(f'\n=== {name} ===', flush=True)
        results[name] = run(command, cwd, timeout=420 if name == 'Dependency audit' else 300)
    for name, ok in results.items():
        print(f'{name}: {"PASS" if ok else "FAIL"}')
    if not all(results.values()):
        print('RELEASE BLOCKED: failed or incomplete automated checks.')
        return 1
    if args.offline:
        print('LOCAL CHECKS PASSED; RELEASE NOT APPROVED (online audit not run).')
        return 2
    print('AUTOMATED CHECKS PASSED; manual staging/TLS/payment/load/pentest checks still required.')
    return 0

if __name__ == '__main__':
    sys.exit(main())
