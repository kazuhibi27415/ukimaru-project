from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import grpc
import requests

import stream_list_pb2
import stream_list_pb2_grpc


LOGGER = logging.getLogger(__name__)

YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3"
GRPC_ENDPOINT = "dns:///youtube.googleapis.com:443"
SUPER_CHAT_EVENT = 15
MAX_SEEN_IDS = 5000


@dataclass(frozen=True)
class SuperChatEvent:
    message_id: str
    author: str
    amount: Decimal
    amount_micros: int
    amount_display: str
    currency: str
    comment: str
    tier: int
    published_at: str


class SeenMessageCache:
    def __init__(self, max_size: int = MAX_SEEN_IDS):
        self.max_size = max_size
        self._queue = deque()
        self._ids: set[str] = set()

    def contains(self, message_id: str) -> bool:
        return message_id in self._ids

    def add(self, message_id: str) -> None:
        if message_id in self._ids:
            return
        if len(self._queue) >= self.max_size:
            old = self._queue.popleft()
            self._ids.discard(old)
        self._queue.append(message_id)
        self._ids.add(message_id)


def extract_video_id(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("YouTube Live URL / Video ID が空です。")

    if "youtube.com" not in value and "youtu.be" not in value:
        return value

    parsed = urlparse(value)

    if parsed.netloc in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/")[0]
        if video_id:
            return video_id

    if parsed.path == "/watch":
        query = parse_qs(parsed.query)
        if query.get("v"):
            return query["v"][0]

    if parsed.path.startswith("/live/"):
        video_id = parsed.path.split("/live/", 1)[1].split("/")[0]
        if video_id:
            return video_id

    raise ValueError("YouTube URLからVideo IDを取得できませんでした。")


def get_live_chat_id(video_id: str, api_key: str) -> str:
    response = requests.get(
        f"{YOUTUBE_API_URL}/videos",
        params={
            "part": "liveStreamingDetails",
            "id": video_id,
            "key": api_key,
        },
        timeout=15,
    )

    if not response.ok:
        body = response.text.strip().replace("\n", " ")[:500]
        raise RuntimeError(
            f"YouTube videos.list 失敗: HTTP {response.status_code} / {body}"
        )

    data = response.json()
    items = data.get("items", [])
    if not items:
        raise RuntimeError("動画が見つかりません。Video ID/APIキーを確認してください。")

    details = items[0].get("liveStreamingDetails", {})
    live_chat_id = details.get("activeLiveChatId")
    if not live_chat_id:
        raise RuntimeError(
            "activeLiveChatId が取得できません。配信中でない、ライブチャット無効、"
            "または配信終了済みの可能性があります。"
        )
    return live_chat_id


def _to_event(message) -> SuperChatEvent:
    snippet = message.snippet
    details = snippet.super_chat_details

    amount_micros = int(details.amount_micros)
    amount = Decimal(amount_micros) / Decimal("1000000")

    author = "Unknown"
    if message.HasField("author_details") and message.author_details.display_name:
        author = message.author_details.display_name

    return SuperChatEvent(
        message_id=message.id,
        author=author,
        amount=amount,
        amount_micros=amount_micros,
        amount_display=details.amount_display_string or str(amount),
        currency=details.currency,
        comment=details.user_comment,
        tier=int(details.tier),
        published_at=snippet.published_at,
    )


def watch_live_chat(
    live_chat_id: str,
    api_key: str,
    ignore_initial_history: bool,
    on_superchat,
) -> None:
    """YouTube gRPC streamList を継続監視する。"""
    seen = SeenMessageCache()
    next_page_token = ""
    initial_batch = True

    metadata = (("x-goog-api-key", api_key),)
    credentials = grpc.ssl_channel_credentials()

    LOGGER.info("[STREAM] YouTube gRPCへ接続中...")

    with grpc.secure_channel(
        GRPC_ENDPOINT,
        credentials,
        options=[
            ("grpc.keepalive_time_ms", 60000),
            ("grpc.keepalive_timeout_ms", 20000),
        ],
    ) as channel:
        try:
            grpc.channel_ready_future(channel).result(timeout=10)
        except grpc.FutureTimeoutError as exc:
            raise RuntimeError("YouTube gRPCサーバーへ接続できませんでした。") from exc

        stub = stream_list_pb2_grpc.V3DataLiveChatMessageServiceStub(channel)
        LOGGER.info("[STREAM] 監視開始")

        while True:
            kwargs = {
                "live_chat_id": live_chat_id,
                "max_results": 200,
                "part": ["id", "snippet", "authorDetails"],
            }
            if next_page_token:
                kwargs["page_token"] = next_page_token

            request = stream_list_pb2.LiveChatMessageListRequest(**kwargs)
            received_response = False

            try:
                for response in stub.StreamList(request, metadata=metadata):
                    received_response = True
                    next_page_token = response.next_page_token or ""

                    if response.offline_at:
                        LOGGER.info("[END] ライブ配信が終了しました。")
                        return

                    if initial_batch and ignore_initial_history:
                        for message in response.items:
                            if message.id:
                                seen.add(message.id)
                        LOGGER.info(
                            "[INIT] %d 件を既読として処理しました。",
                            len(response.items),
                        )
                        initial_batch = False
                        continue

                    initial_batch = False

                    for message in response.items:
                        message_id = message.id
                        if not message_id or seen.contains(message_id):
                            continue
                        seen.add(message_id)

                        if not message.HasField("snippet"):
                            continue
                        snippet = message.snippet
                        if snippet.type != SUPER_CHAT_EVENT:
                            continue
                        if not snippet.HasField("super_chat_details"):
                            continue

                        on_superchat(_to_event(message))

                # 正常EOFは仕様上あり得る。next_page_tokenで即座に次RPCへ進む。
                if not received_response:
                    time.sleep(1)

            except grpc.RpcError as exc:
                code = exc.code()
                details = exc.details()
                LOGGER.error("[gRPC ERROR] %s: %s", code, details)

                if code in (grpc.StatusCode.INVALID_ARGUMENT, grpc.StatusCode.NOT_FOUND):
                    return
                if code == grpc.StatusCode.PERMISSION_DENIED:
                    raise RuntimeError(
                        "YouTube APIキーまたはAPI制限設定を確認してください。"
                    ) from exc
                if code == grpc.StatusCode.RESOURCE_EXHAUSTED:
                    LOGGER.warning("[STREAM] レート制限。5秒後に再試行します。")
                    time.sleep(5)
                    continue

                LOGGER.warning("[STREAM] 3秒後に再試行します。")
                time.sleep(3)
