import configparser
import io
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
import sys
from unittest.mock import MagicMock, patch

from app_config import settings_from_parser
from settings_ui import MonitorProcess, SettingsWindow, save_config
from pavlok_superchat import configure_stdio


def example():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(Path(__file__).with_name('config.ini.example'), encoding='utf-8-sig')
    return parser


class SettingsUiTests(unittest.TestCase):
    def test_gui_worker_overrides_cp932_streams(self):
        streams = [io.TextIOWrapper(io.BytesIO(), encoding='cp932') for _ in range(3)]
        try:
            with patch.object(sys, 'argv', ['app.exe', '--console', '--gui-worker']), \
                    patch.object(sys, 'stdin', streams[0]), patch.object(sys, 'stdout', streams[1]), \
                    patch.object(sys, 'stderr', streams[2]):
                configure_stdio()
                print('設定読み込み OK / ¥500')
                sys.stderr.write('日本円のSuper Chat\n')
            for stream in streams[1:]:
                stream.flush()
                self.assertEqual(stream.encoding, 'utf-8')
            self.assertIn('¥500', streams[1].buffer.getvalue().decode('utf-8'))
            self.assertIn('日本円', streams[2].buffer.getvalue().decode('utf-8'))
        finally:
            for stream in streams:
                stream.close()

    def test_save_roundtrip_preserves_comments_and_validates_before_write(self):
        parser = example()
        with tempfile.NamedTemporaryFile(dir=Path.cwd(), suffix='.ini', delete=False) as handle:
            path = Path(handle.name)
        try:
            original = Path('config.ini.example').read_bytes()
            path.write_bytes(original)
            parser.set('SuperChat3', 'enabled', 'false')
            parser.set('SuperChat4', 'enabled', 'false')
            parser.set('SuperChat1', 'output_mode', 'random')
            parser.set('SuperChat1', 'random_max', '30')
            save_config(parser, path)
            after = configparser.ConfigParser(interpolation=None)
            after.read(path, encoding='utf-8-sig')
            config = settings_from_parser(after, require_youtube_key=False)
            self.assertEqual(len(config.output_groups), 2)
            self.assertEqual(config.output_groups[0].random_max, 30)
            self.assertIn('設定ファイル', path.read_text(encoding='utf-8-sig'))
            self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
            saved = path.read_bytes()
            parser.set('SuperChat1', 'random_max', '101')
            with self.assertRaises(ValueError):
                save_config(parser, path)
            self.assertEqual(path.read_bytes(), saved)
        finally:
            path.unlink(missing_ok=True)

    def test_start_stop_and_restart_use_separate_processes(self):
        processes = []

        def launch(*args, **kwargs):
            process = MagicMock()
            process.poll.return_value = None
            process.stdout = io.StringIO('test log\n')
            process.terminate.side_effect = lambda: setattr(process.poll, 'return_value', -1)
            processes.append(process)
            return process

        monitor = MonitorProcess()
        with patch('settings_ui.subprocess.Popen', side_effect=launch) as popen:
            monitor.start('abcdefghijk')
            monitor.reader.join(1)
            self.assertTrue(monitor.running)
            with self.assertRaises(RuntimeError):
                monitor.start('abcdefghijk')
            monitor.stop()
            self.assertFalse(monitor.running)
            processes[0].terminate.assert_called_once()
            monitor.start('secondvideo')
            monitor.reader.join(1)
            monitor.stop()
            self.assertEqual(popen.call_count, 2)
            self.assertIn('--console', popen.call_args.args[0])
            self.assertIn('--gui-worker', popen.call_args.args[0])
            processes[1].stdin.write.assert_called_once_with('secondvideo\n')

    def test_window_settings_and_start_stop_states(self):
        root = tk.Tk()
        root.withdraw()
        try:
            with patch('settings_ui.get_config_path', return_value=Path('config.ini.example')):
                window = SettingsWindow(root)
            self.assertEqual(len([key for key in window.fields if key[1] == 'output_mode']), 4)
            self.assertEqual(window.fields['SuperChat1', 'output_mode'].get(), '固定')
            window.fields['SuperChat1', 'output_mode'].set('ランダム')
            self.assertEqual(window.collect().get('SuperChat1', 'output_mode'), 'random')
            window.fields['SuperChat3', 'enabled'].set('false')
            window.fields['SuperChat4', 'enabled'].set('false')
            window.fields['YouTube', 'api_key'].set('test-api-key')
            window.video.set('https://www.youtube.com/watch?v=abcdefghijk')
            with patch('settings_ui.save_config') as save, patch.object(window.monitor, 'start') as start:
                window.start()
            save.assert_called_once()
            start.assert_called_once_with('abcdefghijk')
            self.assertEqual(str(window.start_button['state']), 'disabled')
            self.assertEqual(str(window.stop_button['state']), 'normal')
            with patch.object(window.monitor, 'stop') as stop:
                window.stop()
            stop.assert_called_once()
            self.assertTrue(window.stop_requested)
            window.set_running(False)
            self.assertEqual(str(window.start_button['state']), 'normal')
            self.assertEqual(str(window.stop_button['state']), 'disabled')
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
