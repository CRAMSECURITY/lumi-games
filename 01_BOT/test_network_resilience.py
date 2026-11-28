import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from contextlib import closing
import lumi_global_ban as sync

class NetworkTests(unittest.TestCase):
    def test_strict_ack(self):
        for body in [b'{"accepted":false}',b'{"accepted":"true"}',b'[]',b'{"accepted":1}',b'{}',b'{"accepted":true}'+b' '*1025]:
            with self.subTest(body=body[:40]), patch('urllib.request.build_opener') as opener:
                response=opener.return_value.open.return_value.__enter__.return_value
                response.status=200; response.read.return_value=body
                with self.assertRaises(RuntimeError): sync.send('https://example.test','key',1,2,-1)
        with patch('urllib.request.build_opener') as opener:
            response=opener.return_value.open.return_value.__enter__.return_value
            response.status=200; response.read.return_value=b'{"accepted":true}'
            sync.send('https://example.test','key',1,2,-1)
    def test_queue_survives_failure(self):
        with tempfile.TemporaryDirectory() as d:
            def connect(): return sqlite3.connect(Path(d)/'db')
            with closing(connect()) as db,db:
                db.execute('CREATE TABLE account_suspensions(user_id INTEGER PRIMARY KEY, expires_at TEXT)'); sync.init_sync(db)
                db.executemany('INSERT INTO account_suspensions VALUES(?,NULL)',[(1,),(2,),(3,)])
            with patch.object(sync,'send',side_effect=[None,TimeoutError()]):
                with self.assertRaises(TimeoutError): sync.drain(connect,'https://example.test','key')
            with closing(connect()) as db:
                self.assertEqual(db.execute('SELECT uid FROM ban_sync ORDER BY seq').fetchall(),[(2,),(3,)])
            with patch.object(sync,'send') as send:
                sync.drain(connect,'https://example.test','key'); self.assertEqual([x.args[3] for x in send.call_args_list],[2,3])
            with closing(connect()) as db: self.assertEqual(db.execute('SELECT count(*) FROM ban_sync').fetchone()[0],0)
    def test_backoff_bounds(self):
        self.assertEqual(sync.retry_delay(0),10)
        for n in range(1,100):
            ceiling=min(120,10*2**min(n,4)); self.assertLessEqual(sync.retry_delay(n),ceiling); self.assertGreaterEqual(sync.retry_delay(n),ceiling/2)

class LoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovers_and_resets_backoff(self):
        with patch.object(sync.asyncio,'to_thread',new=AsyncMock(side_effect=[TimeoutError(),TimeoutError(),None])), patch.object(sync,'retry_delay',side_effect=[10,20,10]) as delay, patch.object(sync.asyncio,'sleep',new=AsyncMock(side_effect=[None,None,asyncio.CancelledError()])):
            with self.assertRaises(asyncio.CancelledError): await sync.sync_loop(None,'url','secret')
            self.assertEqual([x.args[0] for x in delay.call_args_list],[1,2,0])
