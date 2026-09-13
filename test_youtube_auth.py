"""OAuthの回帰テスト。実アカウント・実API・Pavlokへの通信は行わない。"""
import configparser
import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import grpc
import stream_list_pb2 as pb
import youtube_auth as auth
import youtube_stream as stream
from app_config import settings_from_parser


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client_file = Path(self.directory.name) / 'client.json'
        self.client_file.write_text(json.dumps({'installed': {
            'client_id': 'test.apps.googleusercontent.com', 'client_secret': 'dummy-secret',
            'auth_uri': 'https://untrusted.invalid', 'token_uri': 'https://untrusted.invalid',
        }}))
        self.cache = Path(self.directory.name) / 'youtube_oauth.bin'
        self.patcher = patch.object(auth, 'token_path', return_value=self.cache)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_windows_encryption_and_cache_roundtrip(self):
        plaintext = b'dummy-access-and-refresh-token'
        ciphertext = auth.protect(plaintext)
        self.assertNotIn(plaintext, ciphertext)
        self.assertEqual(auth.protect(ciphertext, decrypt=True), plaintext)
        oauth = auth.YouTubeOAuth(str(self.client_file))
        oauth.credentials = auth.Credentials(
            token='dummy-access', refresh_token='dummy-refresh', token_uri=auth.TOKEN_URI,
            client_id='test.apps.googleusercontent.com', client_secret='dummy-secret', scopes=auth.SCOPES)
        oauth._save()
        self.assertNotIn(b'dummy-refresh', self.cache.read_bytes())
        with patch.object(auth.Credentials, 'refresh') as refresh:
            refresh.side_effect = lambda request: None
            # 保存済み認証の読み込みにブラウザを使わない。
            with patch.object(auth.InstalledAppFlow, 'from_client_config') as flow:
                restored = auth.YouTubeOAuth(str(self.client_file))
                restored.login()
                self.assertEqual(restored.get_access_token(), 'dummy-access')
                flow.assert_not_called()
        auth.forget_login()
        self.assertFalse(self.cache.exists())
        auth.forget_login()

    def test_browser_login_uses_pkce_loopback_and_hides_callback_logs(self):
        oauth = auth.YouTubeOAuth(str(self.client_file))
        with patch.object(auth.InstalledAppFlow, 'from_client_config') as factory, patch.object(oauth, '_save') as save:
            def login(**kwargs):
                self.assertTrue(logging.getLogger('google_auth_oauthlib.flow').disabled)
                self.assertEqual(kwargs['host'], '127.0.0.1')
                self.assertEqual(kwargs['port'], 0)
                self.assertEqual(kwargs['timeout_seconds'], 180)
                return MagicMock(valid=True, refresh_token='dummy')
            factory.return_value.run_local_server.side_effect = login
            oauth.login()
            self.assertTrue(factory.call_args.kwargs['autogenerate_code_verifier'])
            self.assertEqual(factory.call_args.args[0]['installed']['token_uri'], auth.TOKEN_URI)
            save.assert_called_once()

    def test_login_failure_does_not_expose_tokens_or_save(self):
        oauth = auth.YouTubeOAuth(str(self.client_file))
        with patch.object(auth.InstalledAppFlow, 'from_client_config', side_effect=ValueError('secret-token')), \
                patch.object(oauth, '_save') as save:
            with self.assertRaises(RuntimeError) as error:
                oauth.login()
            self.assertNotIn('secret-token', str(error.exception))
            self.assertIsNone(oauth.credentials)
            save.assert_not_called()

    def test_refresh_is_saved_and_failure_is_sanitized(self):
        oauth = auth.YouTubeOAuth(str(self.client_file))
        oauth.credentials = MagicMock(valid=False, token='new-token')
        with patch.object(oauth, '_save') as save:
            self.assertEqual(oauth.get_access_token(), 'new-token')
            oauth.credentials.refresh.assert_called_once()
            save.assert_called_once()
            oauth.credentials.refresh.side_effect = RuntimeError('secret-token')
            with self.assertRaises(RuntimeError) as error:
                oauth.get_access_token(force_refresh=True)
            self.assertNotIn('secret-token', str(error.exception))

    def test_oauth_config_does_not_require_api_key(self):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read('config.ini.example', encoding='utf-8-sig')
        parser.set('YouTube', 'api_key', '')
        parser.set('YouTube', 'auth_mode', 'oauth')
        parser.set('YouTube', 'oauth_client_file', str(self.client_file))
        parser.set('Pavlok', 'enabled', 'false')
        self.assertEqual(settings_from_parser(parser).youtube_auth_mode, 'oauth')
        parser.set('YouTube', 'auth_mode', 'api_key')
        with self.assertRaises(ValueError):
            settings_from_parser(parser)

    def test_rest_401_refresh_once_and_403_does_not_retry(self):
        oauth = MagicMock()
        oauth.get_access_token.side_effect = ['old', 'new']
        success = MagicMock(ok=True, status_code=200)
        success.json.return_value = {'items': [{'liveStreamingDetails': {'activeLiveChatId': 'chat'}}]}
        with patch.object(stream.requests, 'get', side_effect=[MagicMock(ok=False, status_code=401), success]) as get:
            self.assertEqual(stream.get_live_chat_id('video', 'unused', oauth), 'chat')
            self.assertNotIn('key', get.call_args.kwargs['params'])
            self.assertEqual(get.call_args.kwargs['headers'], {'Authorization': 'Bearer new'})
            oauth.get_access_token.assert_called_with(force_refresh=True)
        oauth.get_access_token.side_effect = None
        oauth.get_access_token.return_value = 'token'
        with patch.object(stream.requests, 'get', return_value=MagicMock(ok=False, status_code=403)) as get:
            with self.assertRaises(RuntimeError):
                stream.get_live_chat_id('video', '', oauth)
            self.assertEqual(get.call_count, 1)

    def test_stream_refresh_preserves_page_and_duplicate_cache(self):
        oauth = MagicMock()
        oauth.get_access_token.return_value = 'token'
        error = grpc.RpcError()
        error.code = lambda: grpc.StatusCode.UNAUTHENTICATED
        error.details = lambda: 'secret-token'
        batch = pb.LiveChatMessageListResponse(next_page_token='resume')
        msg = batch.items.add(id='same')
        msg.snippet.type = 15
        msg.snippet.super_chat_details.amount_micros = 500000000
        msg.snippet.super_chat_details.currency = 'JPY'
        def interrupted():
            yield batch
            raise error
        stub = MagicMock()
        stub.StreamList.side_effect = [interrupted(), iter([batch, pb.LiveChatMessageListResponse(offline_at='end')])]
        received = []
        with patch.object(stream.grpc, 'secure_channel'), patch.object(stream.grpc, 'channel_ready_future'), \
                patch.object(stream.stream_list_pb2_grpc, 'V3DataLiveChatMessageServiceStub', return_value=stub):
            stream.watch_live_chat('chat', '', False, received.append, oauth)
        self.assertEqual(len(received), 1)
        self.assertEqual(stub.StreamList.call_args.args[0].page_token, 'resume')
        self.assertEqual(stub.StreamList.call_args.kwargs['metadata'], (('authorization', 'Bearer token'),))
        self.assertEqual(sum(call.kwargs.get('force_refresh', False) for call in oauth.get_access_token.call_args_list), 1)
        stub.StreamList.side_effect = [error, error]
        with patch.object(stream.grpc, 'secure_channel'), patch.object(stream.grpc, 'channel_ready_future'), \
                patch.object(stream.stream_list_pb2_grpc, 'V3DataLiveChatMessageServiceStub', return_value=stub):
            with self.assertRaises(RuntimeError):
                stream.watch_live_chat('chat', '', False, received.append, oauth)
        self.assertEqual(stub.StreamList.call_count, 4)


if __name__ == '__main__':
    unittest.main()
