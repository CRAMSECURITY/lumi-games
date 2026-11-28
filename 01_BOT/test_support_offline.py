"""Offline SQLite migration / threaded-support smoke tests. Run: python test_support_offline.py"""
import ast
import sqlite3
from lumi_test_sqlite import patch_sqlite_connect
patch_sqlite_connect()
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def isolate_function(filename, function):
    parsed=ast.parse((ROOT/filename).read_text(encoding='utf-8'))
    f=next(x for x in parsed.body if isinstance(x,ast.FunctionDef) and x.name==function)
    code=compile(ast.Module(body=[f],type_ignores=[]),filename,'exec')
    ns={'sqlite3':sqlite3}
    exec(code,ns)
    return ns[function],ns

with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)/'test.db'
    db=sqlite3.connect(path)
    # Old (1-message) support schema, proving additive migration.
    db.execute('''CREATE TABLE support_tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        category TEXT DEFAULT 'question', message TEXT NOT NULL,status TEXT DEFAULT 'open',reply TEXT,
        assigned_admin INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    db.execute("INSERT INTO support_tickets(user_id,message) VALUES (101,'старый вопрос')")
    schema,_=isolate_function('bot.py','init_admin_tables')
    schema(db);schema(db)
    assert db.execute('SELECT message FROM support_tickets WHERE id=1').fetchone()[0]=='старый вопрос'
    db.execute("INSERT INTO support_messages(ticket_id,sender,body) VALUES (1,'user','новый вопрос')")
    db.execute("INSERT INTO support_messages(ticket_id,sender,body) VALUES (1,'admin','ответ')")
    db.execute("INSERT INTO support_messages(ticket_id,sender,body) VALUES (1,'user','уточнение')")
    db.execute("UPDATE support_tickets SET status='sending' WHERE id=1 AND status='open'")
    db.execute("UPDATE support_tickets SET status='open' WHERE id=1 AND status='sending'")
    assert db.execute("SELECT status FROM support_tickets WHERE id=1").fetchone()[0]=='open'
    assert [r[0] for r in db.execute('SELECT sender FROM support_messages WHERE ticket_id=1 ORDER BY id')]==['user','admin','user']
    assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    db.commit();db.close()
    admin_schema,ns=isolate_function('lumi_admin.py','init_admin_schema')
    ns['db_connect']=lambda:sqlite3.connect(path)
    admin_schema();admin_schema()
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM support_messages').fetchone()[0]==3
        assert db.execute('SELECT COUNT(*) FROM support_tickets').fetchone()[0]==1
        assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
print('PASS: old tickets retained, both migrations idempotent, multi-message conversation, open-after-reply, quick_check')
