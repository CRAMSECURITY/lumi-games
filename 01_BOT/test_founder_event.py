"""LUMI founders event: isolated offline checks; never opens production lumi.db."""
import ast
import concurrent.futures
import sqlite3
from lumi_test_sqlite import patch_sqlite_connect
patch_sqlite_connect()
import tempfile
from pathlib import Path
from types import SimpleNamespace

source=Path(__file__).with_name('bot.py')
module=ast.parse(source.read_text(encoding='utf-8'))
selected=('connect_db','founder_number','founder_status','claim_founder','founder_badge')
nodes=[n for n in module.body if isinstance(n,ast.FunctionDef) and n.name in selected]
assert len(nodes)==len(selected)
code=compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec')
with tempfile.TemporaryDirectory(prefix='lumi_founders_') as tmp:
    ns={'sqlite3':sqlite3,'DB_PATH':Path(tmp)/'event.db','FOUNDER_LIMIT':100}
    exec(code,ns)
    with ns['connect_db']() as db:
        db.execute('CREATE TABLE profiles (user_id INTEGER PRIMARY KEY, age INTEGER)')
        db.execute('CREATE TABLE lumi_founders(serial INTEGER PRIMARY KEY AUTOINCREMENT, '
                   'user_id INTEGER NOT NULL UNIQUE, awarded_at TEXT DEFAULT CURRENT_TIMESTAMP, '
                   'CHECK(serial BETWEEN 1 AND 100))')
        db.executemany('INSERT INTO profiles(user_id,age) VALUES (?,?)',[(i,22) for i in range(1,110)])
        db.execute('INSERT INTO profiles(user_id,age) VALUES (?,?)',(200,17))
    assert ns['claim_founder'](200)==(None,False)
    assert ns['claim_founder'](9999)==(None,False)
    def claim(i): return ns['claim_founder'](i)
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        vals=list(pool.map(claim,range(1,101)))
    awarded=[v[0] for v in vals]
    assert len(set(awarded))==100 and set(awarded)==set(range(1,101))
    assert ns['claim_founder'](1)==(awarded[0],False)
    assert ns['claim_founder'](101)==(None,False)
    with ns['connect_db']() as db:
        assert ns['founder_status'](db)==(100,0)
        db.execute('DELETE FROM lumi_founders WHERE user_id=100')
        db.execute('DELETE FROM profiles WHERE user_id=100')
    assert ns['claim_founder'](101)==(None,False), 'Deletion must not recycle a founder place'
    with ns['connect_db']() as db:
        assert ns['founder_status'](db)==(100,0)
        assert ns['founder_badge'](db,1).startswith('\n🏅')
        assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
print('PASS: 100 unique places, age/profile checks, concurrent claims, no recycling, sqlite integrity')
