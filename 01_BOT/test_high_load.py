import os
import unittest
from unittest.mock import patch
from lumi_polling import polling_limit, bounded_polling

class Dispatcher:
    async def start_polling(self, bot, *, handle_as_tasks=True, tasks_concurrency_limit=None):
        self.args = (bot, handle_as_tasks, tasks_concurrency_limit)

class OldDispatcher:
    async def start_polling(self, bot, **kwargs):
        raise AssertionError('must not start')

class HighLoadTests(unittest.IsolatedAsyncioTestCase):
    async def test_forward_limit(self):
        with patch.dict(os.environ, {'TEST_LIMIT':'17'}):
            d = Dispatcher(); await bounded_polling(d, 'bot', 'TEST_LIMIT', 32)
            self.assertEqual(d.args, ('bot', True, 17))
    async def test_default(self):
        with patch.dict(os.environ, {}, clear=True):
            d = Dispatcher(); await bounded_polling(d, 'bot', 'TEST_LIMIT', 8)
            self.assertEqual(d.args, ('bot', True, 8))
    async def test_old_version_rejected(self):
        with self.assertRaises(RuntimeError):
            await bounded_polling(OldDispatcher(), 'bot', 'TEST_LIMIT', 32)
    def test_bad_values(self):
        for value in ('0','257','-1','1.5','', '１２', '9999'):
            with self.subTest(value=value), patch.dict(os.environ, {'TEST_LIMIT':value}):
                with self.assertRaises(RuntimeError): polling_limit('TEST_LIMIT', 32)
