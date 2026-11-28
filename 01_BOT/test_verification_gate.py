"""Offline smoke checks for the verification gate; no Telegram token or real DB used."""
import ast
import sqlite3
from lumi_test_sqlite import patch_sqlite_connect
patch_sqlite_connect()
import tempfile
from pathlib import Path

SOURCE = Path(__file__).with_name('bot.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
needed = {'verification_gate_status', 'verification_gate_keyboard', 'show_verification_gate'}
selected = [n for n in TREE.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in needed]
assert len(selected)==3

class Button:
    def __init__(self,**kwargs): self.__dict__.update(kwargs)
class Markup:
    def __init__(self,**kwargs): self.__dict__.update(kwargs)
with tempfile.TemporaryDirectory() as d:
    dbpath = Path(d) / 'test_lumi.db'
    def connect_db(): return sqlite3.connect(dbpath)
    with connect_db() as db:
        db.execute('CREATE TABLE quiz_progress (user_id INTEGER PRIMARY KEY, viewed_count INTEGER NOT NULL DEFAULT 0)')
        db.execute('CREATE TABLE profile_extras (user_id INTEGER PRIMARY KEY, verified INTEGER NOT NULL DEFAULT 0)')
        db.execute('CREATE TABLE verification_requests (user_id INTEGER PRIMARY KEY, status TEXT)')
        db.execute('INSERT INTO quiz_progress VALUES (100,19)')
    ns=dict(connect_db=connect_db, InlineKeyboardButton=Button, InlineKeyboardMarkup=Markup, VERIFY_GATE_AFTER=20)
    compiled=compile(ast.Module(body=selected,type_ignores=[]),'<extracted verification gate>','exec')
    exec(compiled,ns)
    status=ns['verification_gate_status']
    assert status(100)==(19,False,None)
    with connect_db() as db: db.execute('UPDATE quiz_progress SET viewed_count=20 WHERE user_id=100')
    assert status(100)==(20,False,None)
    with connect_db() as db: db.execute("INSERT INTO verification_requests VALUES (100,'review')")
    assert status(100)==(20,False,'review')
    kb=ns['verification_gate_keyboard'](True)
    assert not any(getattr(b,'callback_data','')=='verifygate:start' for row in kb.inline_keyboard for b in row)
    with connect_db() as db: db.execute('INSERT INTO profile_extras VALUES (100,1)')
    assert status(100)==(20,True,'review')
    assert status(101)==(0,False,None)
assert 'text="🛡 Проверка фото", callback_data="ux:verify"' not in SOURCE
assert 'BotCommand(command="verify"' not in SOURCE
assert 'if gate_count >= VERIFY_GATE_AFTER and not gate_approved:' in SOURCE
assert 'if count == VERIFY_GATE_AFTER:' in SOURCE
ADMIN=Path(__file__).with_name('lumi_admin.py').read_text(encoding='utf-8')
assert 'f\'👤 <b>{safe(label,100)}</b>' in ADMIN
assert 'f\'🆔 <code>{user_id}</code>' in ADMIN
print('PASS: start / 19 / 20 / awaiting / approved / unrelated user / hidden manual entry / admin identity')
