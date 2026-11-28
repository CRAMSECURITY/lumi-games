"""Exercise the actual main-bot suspension middleware with fake Telegram events."""
from lumi_test_sqlite import connect as sqlite_test_connect

import asyncio
import ast
import sqlite3
from lumi_test_sqlite import patch_sqlite_connect
patch_sqlite_connect()
import tempfile
from pathlib import Path
from types import SimpleNamespace

source=Path(__file__).with_name('bot.py')
tree=ast.parse(source.read_text(encoding='utf-8'))
node=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='AccountSuspensionGuard')
class BaseMiddleware: pass
class Message:
    def __init__(self, uid, txt='', success=False):
        self.from_user=SimpleNamespace(id=uid)
        self.text=txt
        self.successful_payment=bool(success)
        self.refunded_payment=None
        self.responses=[]
    async def answer(self,msg): self.responses.append(msg)
class CallbackQuery:
    def __init__(self, uid, txt=''):
        self.from_user=SimpleNamespace(id=uid)
        self.data=txt
        self.responses=[]
    async def answer(self,msg,show_alert=False): self.responses.append(msg)
class SupportForm:
    message=SimpleNamespace(state='SupportForm:message')
class FakeState:
    def __init__(self, value=None):self.value=value
    async def get_state(self):return self.value
with tempfile.TemporaryDirectory() as tmp:
    dbpath=Path(tmp)/'lumi.db'
    with sqlite_test_connect(dbpath) as db:
        db.execute('CREATE TABLE account_suspensions(user_id INTEGER PRIMARY KEY,reason TEXT,expires_at TEXT)')
        db.execute("INSERT INTO account_suspensions VALUES (10,'Нарушение правил',NULL)")
        db.execute("INSERT INTO account_suspensions VALUES (20,'Временная блокировка',datetime('now','-1 minute'))")
    ns={'BaseMiddleware':BaseMiddleware,'Message':Message,'CallbackQuery':CallbackQuery,
        'sqlite3':SimpleNamespace(connect=sqlite_test_connect, OperationalError=sqlite3.OperationalError),'DB_PATH':dbpath,'SupportForm':SupportForm}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),ns)
    guard=ns['AccountSuspensionGuard']()
    called=[]
    async def handler(event,data):called.append(event.from_user.id);return 'allowed'
    async def run():
        blocked=Message(10,'/heroes')
        assert await guard(handler,blocked,{'state':FakeState()}) is None
        assert blocked.responses and '/support' in blocked.responses[0]
        assert not called
        assert await guard(handler,Message(10,'/support'),{'state':FakeState()})=='allowed'
        assert await guard(handler,Message(10,'Продолжение переписки'),{'state':FakeState('SupportForm:message')})=='allowed'
        assert await guard(handler,Message(10,'/deleteaccount'),{'state':FakeState()})=='allowed'
        assert await guard(handler,Message(10,'',success=True),{'state':FakeState()})=='allowed'
        denied=CallbackQuery(10,'arena:daily')
        assert await guard(handler,denied,{}) is None and denied.responses
        assert await guard(handler,CallbackQuery(10,'ux:support'),{})=='allowed'
        assert await guard(handler,Message(20,'/heroes'),{})=='allowed'
        assert await guard(handler,Message(30,'/heroes'),{})=='allowed'
    asyncio.run(run())
print('OK: account guard blocks actions, preserves support/deletion/payment, expired ban ignored')
