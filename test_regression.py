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


def settings(**values):
    parser = configparser.ConfigParser()
    parser.read_dict({
        'YouTube': {'api_key': 'test-key'},
        'SuperChat': {'amounts': '500,1000'},
        'Pavlok': {'enabled': 'false', **{k: str(v) for k, v in values.items()}},
    })
    with patch.object(app_config, 'get_config_path', return_value=MagicMock()), \
            patch.object(app_config.configparser, 'ConfigParser', return_value=parser), \
            patch.object(parser, 'read', return_value=['mock.ini']):
        return app_config.load_settings()


class RegressionTests(unittest.TestCase):
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
            self.assertEqual(app_config.get_config_path(), Path.cwd() / 'app' / 'config.ini')

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
            iter([batch([('old', 15)], 'resume')]),
            iter([batch([('old', 15), ('new', 15), ('new', 15), ('sticker', 16)], 'next'),
                  pb.LiveChatMessageListResponse(offline_at='ended')]),
        ]
        received = []
        with patch.object(youtube_stream.grpc, 'secure_channel'), \
                patch.object(youtube_stream.grpc, 'channel_ready_future'), \
                patch.object(youtube_stream.stream_list_pb2_grpc, 'V3DataLiveChatMessageServiceStub', return_value=stub):
            youtube_stream.watch_live_chat('chat', 'test-key', True, received.append)
        self.assertEqual([item.message_id for item in received], ['new'])
        self.assertEqual(stub.StreamList.call_args_list[1].args[0].page_token, 'resume')


if __name__ == '__main__':
    unittest.main()
