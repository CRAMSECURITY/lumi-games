import sqlite3
import unittest
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from contextlib import nullcontext
from lumi_privacy import purge_admin_references

class PrivacyTests(unittest.IsolatedAsyncioTestCase):
    def test_purge_scoped_and_atomic(self):
        db = sqlite3.connect(':memory:')
        try:
            db.executescript("CREATE TABLE reports(id,reporter_id,reported_id); CREATE TABLE admin_events(type,ref_id); INSERT INTO reports VALUES(10,1,2),(11,3,1),(12,2,3); INSERT INTO admin_events VALUES('report',10),('report',11),('report',12),('guard',1),('verification',1),('guard',2),('ticket',1);")
            purge_admin_references(db, 1); db.commit()
            self.assertEqual(db.execute('SELECT * FROM admin_events').fetchall(), [('report',12),('guard',2),('ticket',1)])
        finally: db.close()
    async def test_export_private_and_protected(self):
        tree = ast.parse(Path(__file__).with_name('bot.py').read_text())
        fn = next(n for n in tree.body if getattr(n,'name',None)=='export_my_data'); fn.decorator_list=[]
        db=Mock(); db.execute.return_value.fetchone.side_effect=[('Name',20,'City','Text','x','y',1,1),(3,),(0,)]
        ns=dict(Message=object,connect_db=lambda:nullcontext(db)); exec(compile(ast.Module(body=[fn],type_ignores=[]),'bot.py','exec'),ns)
        msg=SimpleNamespace(chat=SimpleNamespace(type='group'),from_user=SimpleNamespace(id=1),answer=AsyncMock())
        await ns['export_my_data'](msg); msg.answer.assert_not_awaited(); db.execute.assert_not_called()
        msg.chat.type='private'; await ns['export_my_data'](msg)
        self.assertTrue(msg.answer.call_args.kwargs['protect_content']); self.assertIsNone(msg.answer.call_args.kwargs['parse_mode'])
