"""Offline regression tests: python -m unittest -v test_regression"""

import configparser
import threading
import time
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

import app_config
import pavlok_superchat
import stream_list_pb2 as pb
import youtube_stream
from pavlok_api import PavlokAuth, PavlokClient, ZapResult
from test_queue import event
from trigger_worker import TriggerWorker


def settings(*, groups=None, **values):
    parser = configparser.ConfigParser()
    parser.read_dict({
        'YouTube': {'api_key': 'test-key'},
        'SuperChat': {'amounts': '500,1000'},
        'Pavlok': {'enabled': 'false', **{k: str(v) for k, v in values.items()}},
    })
    if groups is not None:
        parser.read_dict(groups)
    with patch.object(app_config, 'get_config_path', return_value=MagicMock()), \
            patch.object(app_config, 'hydrate_pavlok_token', return_value=''), \
            patch.object(app_config.configparser, 'ConfigParser', return_value=parser), \
            patch.object(parser, 'read', return_value=['mock.ini']):
        return app_config.load_settings()


class RegressionTests(unittest.TestCase):
    def test_zap_redirect_is_not_replayed_or_reported_successful(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                auth = PavlokAuth('test-initial')
                auth._runtime_token = 'test-runtime'
                client = PavlokClient(auth)
                sent = []

                class FakeAdapter(requests.adapters.BaseAdapter):
                    def send(self, request, **kwargs):
                        sent.append(request)
                        response = requests.Response()
                        response.status_code = status if len(sent) == 1 else 200
                        response.headers['Location'] = '/redirected-stimulus'
                        response._content = b''
                        response.request = request
                        response.url = request.url
                        return response

                    def close(self):
                        pass

                # Exercise requests' actual redirect handling without network access.
                client.session.mount('https://', FakeAdapter())
                try:
                    result = client.send_zap(20)
                    self.assertEqual(len(sent), 1)
                    self.assertFalse(result.ok)
                    self.assertEqual(result.status_code, status)
                finally:
                    client.session.close()

    def test_malformed_auth_response_does_not_replace_token(self):
        for data in (None, [], 'unexpected', {'user': None},
                     {'user': {'token': 'Bearer'}}, {'user': {'token': '\u65e5\u672c\u8a9e'}}):
            with self.subTest(data=data):
                auth = PavlokAuth('test-initial')
                auth._runtime_token = 'previous-token'
                auth._session = MagicMock()
                auth._session.get.return_value.json.return_value = data
                self.assertFalse(auth.refresh_runtime_token())
                self.assertEqual(auth.get_runtime_token(), 'previous-token')

    def test_four_output_groups(self):
        groups = {f'SuperChat{i}': {'amounts': str(i * 500), 'output_mode': 'fixed',
                                   'fixed_output': str(i * 10)} for i in range(1, 5)}
        groups['SuperChat4'] = {'amounts': '2000,3000', 'output_mode': 'random',
                               'random_min': '35', 'random_max': '45'}
        config = settings(groups=groups)
        self.assertEqual(config.trigger_amounts, frozenset((500, 1000, 1500, 2000, 3000)))
        self.assertEqual(config.group_for_amount(3000).name, 'SuperChat4')
        client = MagicMock()
        complete = threading.Event()
        outputs = []

        def send(output):
            outputs.append(output)
            if len(outputs) == 4:
                complete.set()
            return ZapResult(True, 200, 'OK')

        client.send_zap.side_effect = send
        with patch('trigger_worker.random.randint', return_value=42) as choose:
            worker = TriggerWorker(replace(config, pavlok_enabled=True), client)
            try:
                for number, amount in enumerate((1500, 500, 3000, 1000)):
                    worker.enqueue(event(number, amount))
                self.assertTrue(complete.wait(3))
                self.assertEqual(outputs, [30, 10, 42, 20])
                choose.assert_called_once_with(35, 45)
            finally:
                worker.stop()
                worker.thread.join(1)

    def test_invalid_groups(self):
        base = {f'SuperChat{i}': {'amounts': str(i * 500), 'output_mode': 'fixed',
                                 'fixed_output': '20'} for i in range(1, 5)}
        for change in ({'amounts': '500'}, {'amounts': ''}, {'amounts': '-1'},
                       {'amounts': '500.5'}, {'fixed_output': '101'},
                       {'output_mode': 'invalid'},
                       {'output_mode': 'random', 'random_min': '40', 'random_max': '20'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                settings(groups={**base, 'SuperChat2': {**base['SuperChat2'], **change}})
        with self.assertRaises(ValueError):
            settings(groups={'SuperChat1': base['SuperChat1']})
        with self.assertRaises(ValueError):
            settings(groups={**base, 'SuperChat2': {'amounts': '1000', 'output_mode': 'fixed'}})

    def test_disabled_groups_and_ignored_legacy_output(self):
        groups = {
            'SuperChat1': {'amounts': '500', 'output_mode': 'fixed', 'fixed_output': '25'},
            'SuperChat2': {'amounts': '1000', 'output_mode': 'random', 'random_min': '10', 'random_max': '30'},
            'SuperChat3': {'enabled': 'false'},
            'SuperChat4': {'enabled': 'false', 'amounts': '500', 'fixed_output': 'invalid'},
        }
        config = settings(groups=groups, output_mode='invalid', fixed_output='invalid',
                          random_min='invalid', random_max='invalid')
        self.assertEqual(config.trigger_amounts, frozenset((500, 1000)))
        self.assertEqual(len(config.output_groups), 2)
        self.assertIsNone(config.group_for_amount(3000))
        for group in groups.values():
            group['enabled'] = 'false'
        with self.assertRaisesRegex(ValueError, 'enabled=true'):
            settings(groups=groups)

    def test_every_group_supports_both_modes(self):
        for mode in ('fixed', 'random'):
            groups = {f'SuperChat{i}': {'enabled': 'true', 'amounts': str(i * 500),
                       'output_mode': mode, 'fixed_output': '23',
                       'random_min': '10', 'random_max': '30'} for i in range(1, 5)}
            config = settings(groups=groups)
            worker = TriggerWorker(config, None)
            try:
                with patch('trigger_worker.random.randint', return_value=17) as choose:
                    for group in config.output_groups:
                        self.assertEqual(worker._select_output(group), 23 if mode == 'fixed' else 17)
                    self.assertEqual(choose.call_count, 0 if mode == 'fixed' else 4)
            finally:
                worker.stop()
                worker.thread.join(1)

    def test_invalid_waits_rejected(self):
        for key in ('delay_seconds', 'cooldown_seconds'):
            for value in ('nan', 'NaN', 'inf', '+inf', '-inf', 'Infinity', '-1'):
                with self.subTest(key=key, value=value):
                    with self.assertRaisesRegex(ValueError, key):
                        settings(**{key: value})

    def test_valid_waits_and_output_bounds(self):
        for value in (0, 0.25, 10):
            result = settings(delay_seconds=value, cooldown_seconds=value)
            self.assertEqual(result.delay_seconds, value)
            self.assertEqual(result.cooldown_seconds, value)
        for key in ('fixed_output', 'random_min', 'random_max'):
            for value in (0, 101):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    settings(**{key: value})
        with self.assertRaises(ValueError):
            settings(random_min=40, random_max=20)

    def test_normalization_and_external_config(self):
        self.assertEqual(app_config._normalize_ascii_compact(' test\u3000-key\t', 'key'), 'test-key')
        self.assertEqual(app_config._normalize_bearer_token('Bearer\u3000test-token'), 'test-token')
        with patch.object(app_config.sys, 'frozen', True, create=True), \
                patch.object(app_config.sys, 'executable', str(Path.cwd() / 'app' / 'PavlokSuperChat.exe')):
            with patch.dict(app_config.os.environ, {'LOCALAPPDATA': str(Path.cwd() / 'local-profile')}):
                self.assertEqual(app_config.get_config_path(), Path.cwd() / 'local-profile' / 'PavlokSuperChat' / 'config.ini')

    def test_fifo_delay_cooldown_and_random_selection(self):
        config = replace(settings(), pavlok_enabled=True, delay_seconds=0.03,
                         cooldown_seconds=0.03, output_mode='random')
        client = MagicMock()
        calls = []
        complete = threading.Event()

        def send(output):
            calls.append((output, time.monotonic()))
            if len(calls) == 3:
                complete.set()
            return ZapResult(False, 500, 'mock failure')

        client.send_zap.side_effect = send
        with patch('trigger_worker.random.randint', side_effect=[11, 22, 33]) as choose:
            worker = TriggerWorker(config, client)
            try:
                start = time.monotonic()
                for number in range(3):
                    worker.enqueue(event(number, 500))
                self.assertEqual(choose.call_count, 0)
                self.assertTrue(complete.wait(3), 'Queue did not complete')
                self.assertEqual([output for output, _ in calls], [11, 22, 33])
                self.assertGreaterEqual(calls[0][1] - start, 0.025)
                for previous, current in zip(calls, calls[1:]):
                    self.assertGreaterEqual(current[1] - previous[1], 0.025)
            finally:
                worker.stop()
                worker.thread.join(1)

    def test_shutdown_cancels_waiting_job(self):
        client = MagicMock()
        worker = TriggerWorker(replace(settings(), pavlok_enabled=True, delay_seconds=10), client)
        worker.enqueue(event(1, 500))
        worker.stop()
        worker.thread.join(1)
        self.assertFalse(worker.thread.is_alive())
        client.send_zap.assert_not_called()

    def test_pavlok_no_retry_and_refresh_for_next_job(self):
        for status in (200, 401, 403, 500, None):
            with self.subTest(status=status):
                auth = PavlokAuth('initial-test-token')
                auth._runtime_token = 'old-token'
                auth._session = MagicMock()
                auth._session.get.return_value.json.return_value = {'user': {'token': 'new-token'}}
                client = PavlokClient(auth)
                client.session = MagicMock()
                if status is None:
                    client.session.post.side_effect = requests.Timeout('mock timeout')
                else:
                    client.session.post.return_value = MagicMock(
                        ok=status == 200, status_code=status, text='mock response')
                result = client.send_zap(20)
                self.assertEqual(result.ok, status == 200)
                self.assertEqual(client.session.post.call_count, 1)
                sent = client.session.post.call_args.kwargs
                self.assertEqual(sent['json'], {'stimulus': {'stimulusType': 'zap', 'stimulusValue': 20}})
                self.assertEqual(sent['headers']['Authorization'], 'Bearer old-token')
                self.assertEqual(auth._session.get.call_count, int(status in (401, 403)))
                if status in (401, 403):
                    self.assertTrue(result.runtime_token_refreshed)
                    client.session.post.return_value = MagicMock(ok=True, status_code=200)
                    client.send_zap(20)
                    self.assertEqual(client.session.post.call_args.kwargs['headers']['Authorization'], 'Bearer new-token')

    def test_superchat_currency_and_exact_amount_filter(self):
        def watch_events(**kwargs):
            for item in (event(1, 500), event(2, 501),
                         replace(event(3, 500), currency='USD'),
                         replace(event(4, 500), amount=Decimal('500.5'))):
                kwargs['on_superchat'](item)

        with patch.object(pavlok_superchat, 'load_settings', return_value=settings()), \
                patch('builtins.input', return_value='abcdefghijk'), patch('builtins.print'), \
                patch.object(pavlok_superchat, 'get_live_chat_id', return_value='chat'), \
                patch.object(pavlok_superchat, 'watch_live_chat', side_effect=watch_events), \
                patch.object(pavlok_superchat, 'TriggerWorker') as worker:
            self.assertEqual(pavlok_superchat.main(), 0)
            worker.return_value.enqueue.assert_called_once_with(event(1, 500))
            worker.return_value.stop.assert_called_once()

    def test_stream_history_duplicates_and_eof_resume(self):
        def batch(ids, token):
            response = pb.LiveChatMessageListResponse(next_page_token=token)
            for message_id, kind in ids:
                message = response.items.add(id=message_id)
                message.snippet.type = kind
                message.snippet.super_chat_details.amount_micros = 500000000
                message.snippet.super_chat_details.currency = 'JPY'
            return response

        stub = MagicMock()
        stub.StreamList.side_effect = [
            iter([batch([('chat', 0), ('old', 15), ('sticker-old', 16)], 'resume')]),
            iter([batch([('old', 15), ('new', 15), ('new', 15), ('sticker', 16)], 'next'),
                  pb.LiveChatMessageListResponse(offline_at='ended')]),
        ]
        received = []
        with patch.object(youtube_stream.grpc, 'secure_channel'), \
                patch.object(youtube_stream.grpc, 'channel_ready_future'), \
                patch.object(youtube_stream.stream_list_pb2_grpc, 'V3DataLiveChatMessageServiceStub', return_value=stub), \
                self.assertLogs(youtube_stream.LOGGER, level='INFO') as logs:
            youtube_stream.watch_live_chat('chat', 'test-key', True, received.append)
        self.assertEqual([item.message_id for item in received], ['new'])
        self.assertEqual(stub.StreamList.call_args_list[1].args[0].page_token, 'resume')
        self.assertTrue(any(
            '[INIT] Super Chat 1 件を既読として処理しました。' in line
            for line in logs.output
        ))


if __name__ == '__main__':
    unittest.main()
