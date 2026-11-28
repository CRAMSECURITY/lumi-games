import ast
import asyncio
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock


def load_functions(file, names, namespace):
    tree = ast.parse(Path(__file__).with_name(file).read_text(encoding='utf-8'))
    body = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert len(body) == len(names)
    exec(compile(ast.Module(body=body, type_ignores=[]), file, 'exec'), namespace)
    return namespace


class AsyncPerformanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_reminder_scan_runs_off_event_loop(self):
        loop_thread = threading.get_ident()
        seen_threads = []
        def scan(now):
            seen_threads.append(threading.get_ident())
            return []
        import time
        ns = load_functions('bot.py', {'return_reminder_pass'}, {'asyncio': asyncio, 'time': time, 'reminder_users': scan})
        await ns['return_reminder_pass'](None)
        self.assertEqual(len(seen_threads), 1)
        self.assertNotEqual(seen_threads[0], loop_thread)

    async def test_claim_reminder_runs_off_event_loop(self):
        import time
        loop_thread = threading.get_ident()
        seen_threads = []
        def claim(*args):
            seen_threads.append(threading.get_ident())
            return 0
        ns = load_functions('bot.py', {'return_reminder_pass'}, {'asyncio': asyncio, 'time': time, 'reminder_users': lambda now: [(1, 0, 0, 0)], 'reminder_stage': lambda *args: 1, 'claim_reminder': claim})
        await ns['return_reminder_pass'](None)
        self.assertEqual(len(seen_threads), 1)
        self.assertNotEqual(seen_threads[0], loop_thread)

    def test_reminder_claim_only_returns_count_after_update(self):
        db = Mock()
        db.execute.side_effect = [[], Mock(rowcount=0)]
        from contextlib import nullcontext
        ns = load_functions('bot.py', {'claim_reminder'}, {'connect_db': lambda: nullcontext(db), 'eligible_candidates': lambda uid: ([(2,)], (18,)), 'is_discoverable': lambda *a: True, 'can_notify': lambda *a: True})
        self.assertEqual(ns['claim_reminder'](1, 0, 0, 1, 100), 0)
        db.execute.side_effect = [[], Mock(rowcount=1)]
        self.assertEqual(ns['claim_reminder'](1, 0, 0, 1, 100), 1)

if __name__ == '__main__':
    unittest.main()
