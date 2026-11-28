"""Offline recovery: authenticate and check a backup before writing a NEW file."""
from contextlib import closing
import argparse, os, sqlite3, tempfile
from pathlib import Path
from lumi_backup_crypto import decrypt_snapshot

def restore(source, destination, key):
    source,destination=Path(source),Path(destination)
    for suffix in ('', '-wal', '-shm', '-journal'):
        candidate = Path(str(destination) + suffix)
        if candidate.exists() or candidate.is_symlink():
            raise FileExistsError('Refusing destination with existing database or sidecar')
    data=decrypt_snapshot(source.read_bytes(),key)
    with closing(sqlite3.connect(':memory:')) as db, db:
        db.deserialize(data)
        if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]: raise ValueError('Database integrity check failed')
    fd,tmp=tempfile.mkstemp(prefix='.restore-',dir=destination.parent)
    try:
        with os.fdopen(fd,'wb') as out: out.write(data);out.flush();os.fsync(out.fileno())
        os.link(tmp,destination) # atomic no-overwrite publication; same filesystem
    finally: Path(tmp).unlink(missing_ok=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source');parser.add_argument('destination');args=parser.parse_args()
    key=os.environ.get('LUMI_BACKUP_KEY');
    if not key: parser.error('LUMI_BACKUP_KEY required')
    restore(args.source,args.destination,key);print('Backup verified and restored to new file. Stop bot before manual replacement.')
if __name__=='__main__':main()
