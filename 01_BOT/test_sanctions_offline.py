"""Offline tests against temporary SQLite database. No Telegram token needed."""
import ast
import sqlite3
from lumi_test_sqlite import patch_sqlite_connect
patch_sqlite_connect()
import tempfile
from pathlib import Path

SOURCE = Path(__file__).with_name('lumi_admin.py')
module = ast.parse(SOURCE.read_text(encoding='utf-8'))
selected = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name in {'apply_sanction','sanction_duration','audit','init_admin_schema'}]
code = compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), 'exec')
with tempfile.TemporaryDirectory() as tmp:
    database = Path(tmp) / 'test.db'
    def db_connect():
        return sqlite3.connect(database)
    namespace={'sqlite3':sqlite3,'db_connect':db_connect}
    exec(code,namespace)
    with db_connect() as db:
        db.execute('CREATE TABLE profiles(user_id INTEGER PRIMARY KEY)')
        db.execute('INSERT INTO profiles(user_id) VALUES (11),(22),(33),(44)')
        # Old-style database before upgrade
        db.execute('CREATE TABLE moderation_holds(user_id INTEGER PRIMARY KEY, reason TEXT NOT NULL, moderator_id INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        db.execute("INSERT INTO moderation_holds(user_id,reason,moderator_id) VALUES(44,'старое ограничение',123)")
    namespace['init_admin_schema']()
    namespace['init_admin_schema']()  # idempotence
    with db_connect() as db:
        assert 'expires_at' in {c[1] for c in db.execute('PRAGMA table_info(moderation_holds)')}
        assert namespace['apply_sanction'](db,11,123,'Нарушение правил общения','day')=='created'
        assert namespace['apply_sanction'](db,11,123,'Повторное ограничение','week')=='already'
        assert namespace['apply_sanction'](db,22,123,'Нецензурные оскорбления','week')=='created'
        assert namespace['apply_sanction'](db,33,123,'Систематическое нарушение правил','forever')=='created'
        assert namespace['apply_sanction'](db,44,123,'Нельзя обойти старый запрет','day')=='already'
        assert namespace['apply_sanction'](db,99,123,'Несуществующий пользователь','day')=='missing'
        assert namespace['apply_sanction'](db,11,123,'test','day')=='invalid'
        row=db.execute('SELECT expires_at FROM moderation_holds WHERE user_id=33').fetchone()
        assert row==(None,)
        row=db.execute('SELECT expires_at > CURRENT_TIMESTAMP FROM moderation_holds WHERE user_id=11').fetchone()
        assert row==(1,)
        db.execute("UPDATE moderation_holds SET expires_at=datetime('now','-1 minute') WHERE user_id=11")
        assert db.execute('SELECT 1 FROM moderation_holds WHERE user_id=11 AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)').fetchone() is None
        assert namespace['apply_sanction'](db,11,123,'Повторное нарушение правил','week')=='created'
        assert namespace['apply_sanction'](db,22,123,'Повторное нарушение','day',scope='account')=='created'
        assert namespace['apply_sanction'](db,22,123,'Повторное нарушение','day',scope='account')=='already'
        assert namespace['apply_sanction'](db,33,123,'Повторное нарушение','forever',scope='account')=='created'
        assert db.execute('SELECT expires_at FROM account_suspensions WHERE user_id=33').fetchone()==(None,)
        assert db.execute("SELECT COUNT(*) FROM moderation_history WHERE action='restrict_profile'").fetchone()[0]==4
        assert db.execute('SELECT reason FROM moderation_holds WHERE user_id=11').fetchone()[0]=='Повторное нарушение правил'
    with db_connect() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
print('OK: migration, duplicate protection, 24h/7d/permanent, expiry, custom reason, audit, SQLite integrity')
