"""Test-only SQLite connection helper for Windows TemporaryDirectory cleanup.
Unlike sqlite3.Connection, this subclass closes on leaving a with-block.
"""
import sqlite3

_ORIGINAL_CONNECT = sqlite3.connect

class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()

def connect(*args, **kwargs):
    kwargs.setdefault('factory', ClosingConnection)
    return _ORIGINAL_CONNECT(*args, **kwargs)

def patch_sqlite_connect():
    """Only call from standalone offline tests; NEVER from production bot."""
    sqlite3.connect = connect
