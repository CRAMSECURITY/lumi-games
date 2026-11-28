"""Offline rehearsal; never replace the live database. Use a private directory."""
import argparse
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from lumi_restore import restore

REQUIRED = {'profiles': {'user_id','name','age','city','interests','photo_id'}, 'premium_orders': {'payload','user_id','price','status','created_at'}, 'premium_payments': {'charge_id','payload','user_id','stars','paid_at','refunded'}}

def drill(source, key, workspace):
    with tempfile.TemporaryDirectory(prefix='lumi-drill-', dir=workspace) as directory:
        target = Path(directory) / 'rehearsal.sqlite'
        restore(source, target, key)
        with closing(sqlite3.connect(target.as_uri()+'?mode=ro', uri=True)) as db:
            db.execute('PRAGMA trusted_schema=OFF')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table, columns in REQUIRED.items():
                if table not in tables or not columns.issubset({r[1] for r in db.execute(f'PRAGMA table_info({table})')}):
                    raise ValueError('Required LUMI schema missing: '+table)
            if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise ValueError('Foreign key check failed')
    return len(REQUIRED)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source'); parser.add_argument('workspace', type=Path)
    args = parser.parse_args()
    key = os.environ.get('LUMI_BACKUP_KEY')
    if not key: parser.error('LUMI_BACKUP_KEY required')
    try:
        count = drill(args.source, key, args.workspace.resolve())
    except Exception:
        parser.exit(1, 'Recovery rehearsal failed; no live database was replaced.\n')
    print(f'Recovery rehearsal passed ({count} essential tables); no live database replaced.')

if __name__ == '__main__': main()
