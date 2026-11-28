"""Local, read-only operational probe. Run under the bot's trusted OS account."""
import argparse
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path


def probe(path, *, slow_ms=500, error_limit=20):
    if not 1 <= slow_ms <= 60000 or not 1 <= error_limit <= 1000000:
        raise ValueError('Invalid thresholds')
    started = time.monotonic()
    result = {'status': 'unavailable'}
    try:
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            return result
        deadline = started + 3
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA trusted_schema=OFF')
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            rows = db.execute("SELECT metric,count FROM lumi_ops_daily WHERE day=date('now') AND metric IN ('update','slow','error')").fetchall()
            db.execute('SELECT user_id FROM profiles LIMIT 0')
        metrics = dict(rows)
        if any(type(n) is not int or n < 0 for n in metrics.values()):
            return result
        elapsed = round((time.monotonic()-started)*1000, 2)
        errors = metrics.get('error', 0)
        result = {'status': 'degraded' if elapsed >= slow_ms or errors >= error_limit else 'ok',
                  'db_probe_ms': elapsed, 'updates_today': metrics.get('update', 0),
                  'slow_today': metrics.get('slow', 0), 'errors_today': errors}
    except (OSError, sqlite3.Error, ValueError):
        pass
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--slow-ms', type=int, default=500)
    parser.add_argument('--error-limit', type=int, default=20)
    args = parser.parse_args()
    try:
        result = probe(args.database, slow_ms=args.slow_ms, error_limit=args.error_limit)
    except ValueError:
        parser.error('Invalid thresholds')
    print(json.dumps(result, sort_keys=True))
    return {'ok': 0, 'degraded': 1, 'unavailable': 2}[result['status']]


if __name__ == '__main__':
    raise SystemExit(main())
