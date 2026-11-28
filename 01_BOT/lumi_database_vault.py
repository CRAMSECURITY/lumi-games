"""Local SQLite hardening. Not database encryption; use encrypted storage and ACLs."""
import os
import sqlite3
import stat
from pathlib import Path


def private_process_files():
    # Call once at process startup, before any worker threads or database opens.
    if os.name == 'posix':
        os.umask(0o077)


def protect_database_files(path):
    path = Path(path)
    for suffix in ('', '-wal', '-shm', '-journal'):
        candidate = Path(str(path) + suffix)
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError('Unsafe SQLite file type or hard link')
        if os.name == 'posix':
            try:
                # Avoid following a substituted symlink when tightening permissions.
                fd = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            except FileNotFoundError:
                if suffix:
                    continue  # transient journal removed by another connection
                raise
            try:
                current = os.fstat(fd)
                if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
                    raise RuntimeError('Unsafe SQLite file type or hard link')
                if stat.S_IMODE(current.st_mode) != 0o600:
                    os.fchmod(fd, 0o600)
            finally:
                os.close(fd)


class ClosingConnection(sqlite3.Connection):
    """Commit or roll back normally, then release the connection."""
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect_private(path, timeout=10):
    path = Path(path)
    protect_database_files(path)
    if os.name == 'posix':
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
    db = sqlite3.connect(path, timeout=timeout, factory=ClosingConnection)
    try:
        db.execute('PRAGMA secure_delete=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA temp_store=MEMORY')
        protect_database_files(path)
        return db
    except BaseException:
        db.close()
        raise
