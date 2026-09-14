import os
import io
import queue
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import requests
import release_check
import session_logs
import settings_ui


class DesktopFeaturesTests(unittest.TestCase):
    def test_monitor_saves_even_when_screen_queue_is_full(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor = settings_ui.MonitorProcess()
            monitor.secrets = ['private-value']
            monitor.messages = queue.Queue(maxsize=1)
            process = MagicMock(stdout=io.StringIO('first private-value\nsecond\n'))
            with patch.object(session_logs, 'log_dir', return_value=Path(directory)):
                monitor._read(process)
            saved = next(Path(directory).glob('*.log')).read_text(encoding='utf-8')
            self.assertIn('second', saved)
            self.assertNotIn('private-value', saved)
            self.assertTrue(process.stdout.closed)

    def test_release_versions_and_failures(self):
        response = MagicMock()
        with patch.object(release_check.requests, 'get', return_value=response):
            for tag, expected in [('v2.2', 'v2.2'), ('v2.10', 'v2.10'), ('v2.1.0', None),
                                  ('v2.0', None), ('v3.0-rc1', None), (None, None)]:
                response.json.return_value = {'tag_name': tag, 'draft': False, 'prerelease': False}
                self.assertEqual(release_check.newer_release('2.1'), expected)
            response.json.return_value = {'tag_name': 'v3.0', 'prerelease': True}
            self.assertIsNone(release_check.newer_release('2.1'))
            response.json.return_value = []
            self.assertIsNone(release_check.newer_release('2.1'))
        with patch.object(release_check.requests, 'get', side_effect=requests.Timeout):
            self.assertIsNone(release_check.newer_release('2.1'))

    def test_log_redaction_and_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            log = session_logs.SessionLog(['my-private-value'], directory)
            log.write('my-private-value Bearer runtime-secret api_key=private-key "refresh_token": "refresh-secret"\n')
            text = log.path.read_text(encoding='utf-8')
            for secret in ['my-private-value', 'runtime-secret', 'private-key', 'refresh-secret']:
                self.assertNotIn(secret, text)
            with patch.object(session_logs, 'MAX_BYTES', 256):
                for _ in range(8):
                    log.write('あ' * 100 + '\n')
                self.assertLessEqual(log.path.stat().st_size, 256)
                self.assertLessEqual(log.path.with_suffix('.log.1').stat().st_size, 256)
                log.path.read_text(encoding='utf-8')
            log.close()

    def test_retention_preserves_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            unrelated = folder / 'personal.log'
            unrelated.write_text('keep')
            for i in range(12):
                name = f'session-20200101-{i:06d}-' + 'a' * 32 + '.log'
                (folder / name).write_text('old session')
            log = session_logs.SessionLog(directory=folder)
            self.assertEqual(len(list(folder.glob('session-*.log'))), 10)
            for path in folder.glob('session-*.log'):
                if path != log.path:
                    os.utime(path, (time.time() - 8 * 86400,) * 2)
            log.cleanup()
            self.assertEqual(list(folder.glob('session-*.log')), [log.path])
            self.assertTrue(unrelated.exists())

    def test_disk_failure_does_not_break_monitoring(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(Path, 'mkdir', side_effect=PermissionError):
                log = session_logs.SessionLog(directory=directory)
            self.assertTrue(log.failed)
            log.write('still monitoring')
            log.close()


if __name__ == '__main__':
    unittest.main()
