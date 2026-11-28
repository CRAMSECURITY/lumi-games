import unittest
from unittest.mock import patch
from pathlib import Path
import subprocess
import release_gate as gate

class ReleaseGateTests(unittest.TestCase):
    def test_offline_never_approves(self):
        with patch.object(gate, 'run', return_value=True):
            self.assertEqual(gate.main(['--offline']), 2)
    def test_failure_blocks(self):
        with patch.object(gate, 'run', side_effect=[True, False, True, True, True]):
            self.assertEqual(gate.main(['--offline']), 1)
    def test_strict_has_online_and_runtime_checks(self):
        rows = list(gate.checks(Path('/test'), 'python', 'node', False))
        self.assertEqual(len(rows), 7)
        self.assertNotIn('--offline', rows[4][1])
    def test_timeout_blocks(self):
        with patch.object(gate.subprocess, 'run', side_effect=subprocess.TimeoutExpired('test', 1)):
            self.assertFalse(gate.run(['test'], Path('.')))
    def test_missing_tool_blocks(self):
        with patch.object(gate.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertFalse(gate.run(['test'], Path('.')))
