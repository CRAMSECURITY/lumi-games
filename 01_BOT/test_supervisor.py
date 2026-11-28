import asyncio
import unittest
from unittest.mock import AsyncMock, Mock
from lumi_supervisor import supervise, stop_workers

class SupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_and_backoff(self):
        factory=AsyncMock(side_effect=[ValueError('private-token'),None,RuntimeError(),RuntimeError(),RuntimeError(),RuntimeError(),RuntimeError(),asyncio.CancelledError()])
        sleep=AsyncMock(); logger=Mock()
        with self.assertRaises(asyncio.CancelledError):
            await supervise('test',factory,logger,sleep=sleep,clock=lambda:0)
        self.assertEqual([x.args[0] for x in sleep.await_args_list],[5,10,20,40,80,120,120])
        self.assertNotIn('private-token',str(logger.mock_calls))
    async def test_reset_after_healthy_runtime(self):
        factory=AsyncMock(side_effect=[RuntimeError(),RuntimeError(),asyncio.CancelledError()]); sleep=AsyncMock()
        clock=iter([0,1,2,400,401])
        with self.assertRaises(asyncio.CancelledError):
            await supervise('test',factory,Mock(),sleep=sleep,clock=lambda:next(clock))
        self.assertEqual([x.args[0] for x in sleep.await_args_list],[5,5])
    async def test_shutdown_all(self):
        started=asyncio.Event(); stopped=[]
        async def worker():
            started.set()
            try: await asyncio.Event().wait()
            finally: stopped.append(True)
        tasks=[asyncio.create_task(worker()) for _ in range(3)]
        await started.wait(); await asyncio.sleep(0)
        await stop_workers(*tasks,None)
        self.assertEqual(len(stopped),3)
        self.assertTrue(all(t.cancelled() for t in tasks))
    async def test_cancel_during_backoff(self):
        factory=AsyncMock(side_effect=RuntimeError()); entered=asyncio.Event()
        async def sleep(delay):
            entered.set(); await asyncio.Event().wait()
        task=asyncio.create_task(supervise('test',factory,Mock(),sleep=sleep))
        await entered.wait(); await stop_workers(task)
        self.assertEqual(factory.await_count,1)
