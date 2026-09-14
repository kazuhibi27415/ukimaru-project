"""Pavlokトークンの暗号化・旧INI移行。実APIには接続しない。"""
import configparser
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app_config
import pavlok_secret
from settings_ui import save_config


class PavlokSecretTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.secret = self.base / 'profile' / 'pavlok_initial_token.bin'
        self.patcher = patch.object(pavlok_secret, 'token_path', return_value=self.secret)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def parser(self):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read('config.ini.example', encoding='utf-8-sig')
        parser.set('Pavlok', 'enabled', 'false')
        return parser

    def test_encrypted_roundtrip_and_delete(self):
        pavlok_secret.save_token('dummy-private-token')
        self.assertNotIn(b'dummy-private-token', self.secret.read_bytes())
        self.assertEqual(pavlok_secret.load_token(), 'dummy-private-token')
        pavlok_secret.save_token('')
        self.assertFalse(self.secret.exists())

    def test_plaintext_ini_is_migrated_without_changing_other_settings(self):
        path = self.base / 'config.ini'
        parser = self.parser()
        parser.set('Pavlok', 'initial_token', 'Bearer dummy-migration-token')
        with path.open('w', encoding='utf-8-sig') as handle:
            parser.write(handle)
        app_config.hydrate_pavlok_token(parser, path, migrate=True)
        self.assertEqual(parser.get('Pavlok', 'initial_token'), 'dummy-migration-token')
        self.assertEqual(pavlok_secret.load_token(), 'dummy-migration-token')
        disk = configparser.ConfigParser(interpolation=None)
        disk.read(path, encoding='utf-8-sig')
        self.assertEqual(disk.get('Pavlok', 'initial_token'), '')
        self.assertEqual(disk.get('Pavlok', 'delay_seconds'), parser.get('Pavlok', 'delay_seconds'))
        app_config.hydrate_pavlok_token(disk)
        self.assertEqual(disk.get('Pavlok', 'initial_token'), 'dummy-migration-token')

    def test_gui_save_never_writes_plaintext(self):
        path = self.base / 'config.ini'
        path.write_bytes(Path('config.ini.example').read_bytes())
        parser = self.parser()
        parser.set('Pavlok', 'initial_token', 'dummy-new-token')
        save_config(parser, path)
        self.assertNotIn(b'dummy-new-token', path.read_bytes())
        self.assertEqual(pavlok_secret.load_token(), 'dummy-new-token')
        disk = configparser.ConfigParser(interpolation=None)
        disk.read(path, encoding='utf-8-sig')
        self.assertEqual(disk.get('Pavlok', 'initial_token'), '')

    def test_corrupt_secret_has_sanitized_error(self):
        self.secret.parent.mkdir(parents=True)
        self.secret.write_bytes(b'not-dpapi')
        with self.assertRaises(RuntimeError) as error:
            pavlok_secret.load_token()
        self.assertNotIn('not-dpapi', str(error.exception))


if __name__ == '__main__':
    unittest.main()
