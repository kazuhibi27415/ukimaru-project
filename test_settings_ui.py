import configparser
import io
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
import sys
import os
from unittest.mock import MagicMock, patch

from app_config import settings_from_parser, ensure_config_exists
from settings_ui import MonitorProcess, SettingsWindow, save_config, clipboard_action, add_clipboard_menu
from tkinter import ttk
from pavlok_superchat import configure_stdio, report_fatal
from app_version import VERSION


def example():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(Path(__file__).with_name('config.ini.example'), encoding='utf-8-sig')
    # 利用者が設定例を編集しても、テストの入力条件を一定にする。
    parser.set('Pavlok', 'enabled', 'false')
    for i in range(1, 5):
        parser.set(f'SuperChat{i}', 'output_mode', 'fixed')
    return parser


class SettingsUiTests(unittest.TestCase):
    def test_clipboard_inputs_and_readonly_log(self):
        # OSのクリップボードは変更せず、ウィジェットの編集・イベント処理を検証する。
        clipboard = {'value': ''}
        for name, effect in (
            ('clipboard_get', lambda **kwargs: clipboard['value']),
            ('clipboard_clear', lambda **kwargs: clipboard.update(value='')),
            ('clipboard_append', lambda value, **kwargs: clipboard.update(value=clipboard['value'] + value)),
        ):
            patcher = patch.object(tk.Misc, name, side_effect=effect)
            patcher.start()
            self.addCleanup(patcher.stop)
        root = tk.Tk()
        root.withdraw()
        try:
            original = root.clipboard_get()
        except tk.TclError:
            original = None
        try:
            entry = ttk.Entry(root, show='*')
            add_clipboard_menu(entry)
            entry.insert(0, 'test-token')
            clipboard_action(entry, 'select_all')
            clipboard_action(entry, 'copy')
            self.assertEqual(root.clipboard_get(), 'test-token')
            root.clipboard_clear()
            root.clipboard_append('日本語\n500')
            entry.event_generate('<<Paste>>')
            self.assertEqual(entry.get(), '日本語500')
            clipboard_action(entry, 'select_all')
            clipboard_action(entry, 'cut')
            self.assertEqual(entry.get(), '')
            self.assertEqual(root.clipboard_get(), '日本語500')
            entry.configure(state='disabled')
            clipboard_action(entry, 'paste')
            self.assertEqual(entry.get(), '')
            log = tk.Text(root)
            log.insert('1.0', 'ログ ¥500')
            log.configure(state='disabled')
            clipboard_action(log, 'select_all')
            clipboard_action(log, 'copy')
            self.assertEqual(root.clipboard_get(), 'ログ ¥500')
            clipboard_action(log, 'cut')
            self.assertEqual(log.get('1.0', 'end-1c'), 'ログ ¥500')
        finally:
            root.clipboard_clear()
            if original is not None:
                root.clipboard_append(original)
            root.destroy()

    def test_frozen_first_start_and_existing_settings(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            base = Path(directory)
            bundle = base / 'bundle'
            bundle.mkdir()
            default = Path('config.defaults.ini').read_bytes()
            (bundle / 'config.defaults.ini').write_bytes(default)
            with patch.object(sys, 'frozen', True, create=True), \
                    patch.object(sys, '_MEIPASS', str(bundle), create=True), \
                    patch.dict(os.environ, {'LOCALAPPDATA': str(base / 'profile')}):
                path = ensure_config_exists()
                self.assertEqual(path, base / 'profile' / 'PavlokSuperChat' / 'config.ini')
                self.assertEqual(path.read_bytes(), default)
                path.write_bytes(b'; existing user settings\r\n')
                self.assertEqual(ensure_config_exists(), path)
                self.assertEqual(path.read_bytes(), b'; existing user settings\r\n')

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
            with patch('settings_ui.save_token'):
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
                with patch('settings_ui.save_token'):
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
            fixture = example()
            with patch('settings_ui.ensure_config_exists', return_value=Path('config.ini.example')), \
                    patch('settings_ui.hydrate_pavlok_token'), \
                    patch('settings_ui.hydrate_youtube_client'), \
                    patch('settings_ui.configparser.ConfigParser', return_value=fixture), \
                    patch.object(fixture, 'read', return_value=['mock.ini']):
                window = SettingsWindow(root)
            self.assertIn(f'v{VERSION}', root.title())
            window.release_results.put('v9.0')
            window.poll()
            self.assertIn('v9.0', window.update_label.cget('text'))
            self.assertEqual(len([key for key in window.fields if key[1] == 'output_mode']), 4)
            self.assertEqual(window.fields['SuperChat1', 'output_mode'].get(), '固定')
            self.assertEqual(window.fields['YouTube', 'auth_mode'].get(), 'APIキー（公開配信）')
            window.fields['YouTube', 'auth_mode'].set('Googleログイン（メン限向け）')
            self.assertEqual(window.collect().get('YouTube', 'auth_mode'), 'oauth')
            window.fields['YouTube', 'auth_mode'].set('APIキー（公開配信）')
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

    def test_gui_worker_fatal_does_not_wait_for_closed_stdin(self):
        with patch.object(sys, 'argv', ['PavlokSuperChat.exe', '--console', '--gui-worker']), \
                patch('builtins.input') as wait, patch('builtins.print'):
            self.assertEqual(report_fatal(RuntimeError('original failure')), 1)
            wait.assert_not_called()
        with patch.object(sys, 'argv', ['PavlokSuperChat.exe', '--console']), \
                patch('builtins.input', side_effect=EOFError) as wait, patch('builtins.print'):
            self.assertEqual(report_fatal(RuntimeError('original failure')), 1)
            wait.assert_called_once()


if __name__ == '__main__':
    unittest.main()
