import ast
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from lumi_database_vault import connect_private
def load_functions(file, names, namespace):
    tree=ast.parse(Path(__file__).with_name(file).read_text(encoding="utf-8"))
    body=[n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name in names]
    for n in body: n.decorator_list=[]; n.returns=None; [setattr(a,"annotation",None) for a in n.args.args]
    exec(compile(ast.Module(body=body,type_ignores=[]),file,"exec"),namespace)
    return namespace

class ConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_daily_error_releases_lock_before_network(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db.sqlite'
            def connect(): return connect_private(path, timeout=1)
            with connect() as db:
                db.execute('CREATE TABLE t(x)')
            async def answer(*args, **kwargs):
                with connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    db.execute('INSERT INTO t VALUES (1)')
            ns=load_functions('bot.py', {'daily4_claim'}, dict(asyncio=asyncio, connect_db=connect, profile_of=lambda uid: True, eligible_for_reward=lambda *args: False))
            await ns['daily4_claim'](SimpleNamespace(from_user=SimpleNamespace(id=1),answer=answer))
            with connect() as db: self.assertEqual(db.execute('SELECT count(*) FROM t').fetchone()[0],1)
    async def test_duo_error_releases_lock_before_network(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db.sqlite'
            def connect(): return connect_private(path, timeout=1)
            with connect() as db:
                db.execute('CREATE TABLE duo_adventures(user_a,user_b,step,text_a,text_b)')
            async def answer(*args, **kwargs):
                with connect() as db: db.execute('BEGIN IMMEDIATE')
            ns=load_functions('bot.py', {'duo_answer'}, dict(asyncio=asyncio, connect_db=connect))
            await ns['duo_answer'](SimpleNamespace(from_user=SimpleNamespace(id=1),text='/duoanswer hello',answer=answer))
    def test_explicit_transactions_do_not_await(self):
        tree=ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.With) and any(isinstance(x,ast.Constant) and x.value=='BEGIN IMMEDIATE' for x in ast.walk(node)):
                self.assertFalse(any(isinstance(x,ast.Await) for x in ast.walk(node)),node.lineno)
