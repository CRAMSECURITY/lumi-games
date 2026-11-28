"""Offline backup readiness check; does not modify backups or live data."""
import argparse
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from lumi_recovery_drill import drill


def assess(directory, workspace, key, max_age_hours=36, now=None):
    if not 1 <= max_age_hours <= 720:
        raise ValueError('Invalid freshness threshold')
    now = now or datetime.now(timezone.utc)
    directory, workspace = Path(directory), Path(workspace)
    if any(p.is_symlink() or not p.is_dir() for p in (directory, workspace)):
        raise ValueError('Private existing directories required')
    if os.name == 'posix':
        for p in (directory, workspace):
            info = p.stat()
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('Private directories required')
    candidates = []
    for path in directory.glob('lumi_????-??-??.db.enc'):
        try:
            info = path.lstat()
            day = datetime.strptime(path.name[5:15], '%Y-%m-%d').date()
        except (OSError, ValueError):
            continue
        age = now.timestamp() - info.st_mtime
        if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and day <= now.date() and 0 <= age <= max_age_hours * 3600:
            candidates.append((info.st_mtime, path))
    # Do not silently fall back to an older copy if the newest is corrupt.
    if not candidates:
        raise ValueError('No fresh backup')
    _, latest = max(candidates)
    drill(latest, key, workspace.resolve())
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory'); parser.add_argument('workspace')
    parser.add_argument('--max-age-hours', type=int, default=36)
    args = parser.parse_args()
    try:
        assess(args.directory, args.workspace, os.environ['LUMI_BACKUP_KEY'], args.max_age_hours)
    except Exception:
        parser.exit(1, 'BACKUP READINESS FAILED; inspect privately.\n')
    print('BACKUP READINESS PASSED (local rehearsal only).')

if __name__ == '__main__':
    main()
