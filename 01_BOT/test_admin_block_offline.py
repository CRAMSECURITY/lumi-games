"""Offline checks: one-click moderation action (two-stage confirm), no real user data."""
import ast
import sqlite3
from lumi_test_sqlite import patch_sqlite_connect
patch_sqlite_connect()
import tempfile
from pathlib import Path

root = Path(__file__).parent
admin = (root/'lumi_admin.py').read_text(encoding='utf-8')
main = (root/'bot.py').read_text(encoding='utf-8')
assert "f'adm:blockask:{uid}'" in admin
assert "f'adm:blockask:{user_id}'" in admin
assert "f'adm:blockask:{row[1]}'" in admin
assert "adm:sanctionconfirm" in admin
assert "if action=='blockask':" in admin
assert 'user.id not in ADMINS' in admin
assert 'status=\'review\'' in main
assert "SELECT COUNT(*) FROM verification_requests WHERE status='review'" in main
assert 'mh.expires_at IS NULL OR mh.expires_at > CURRENT_TIMESTAMP' in main

nodes = ast.parse(admin).body
fns=[n for n in nodes if isinstance(n, ast.FunctionDef) and n.name in ('apply_profile_hold','audit')]
ns={}
exec(compile(ast.Module(body=fns,type_ignores=[]), '<test>', 'exec'), ns)
with tempfile.TemporaryDirectory() as tmp:
    with sqlite3.connect(str(Path(tmp)/'smoke.db')) as db:
        db.execute('CREATE TABLE profiles(user_id INTEGER PRIMARY KEY, name TEXT)')
        db.execute('CREATE TABLE moderation_holds(user_id INTEGER PRIMARY KEY,reason TEXT,moderator_id INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        db.execute('CREATE TABLE admin_audit(actor_id INTEGER,action TEXT,target_id INTEGER)')
        db.execute("INSERT INTO profiles VALUES (101,'User')")
        apply=ns['apply_profile_hold']
        assert apply(db,101,0)=='invalid'
        assert apply(db,-1,22)=='invalid'
        assert apply(db,999,22)=='missing'
        assert apply(db,101,22)=='created'
        assert apply(db,101,22)=='already'
        assert db.execute('SELECT COUNT(*) FROM moderation_holds').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM admin_audit').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM profiles').fetchone()[0]==1
        db.execute('DELETE FROM moderation_holds WHERE user_id=101')
        assert apply(db,101,23)=='created'
        assert db.execute('SELECT moderator_id FROM moderation_holds').fetchone()[0]==23
        assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
print('PASS: block flow / authorization / no double-audit / reversible / no profile deletion / privacy count')
# Deletion must not immediately remove an active moderation hold.
assert 'DELETE FROM moderation_holds WHERE user_id=?' not in main
assert 'UPDATE moderation_holds SET created_at=CURRENT_TIMESTAMP WHERE user_id=?' in main
assert "created_at < datetime('now','-30 days')" in main
