from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from threading import Lock

import requests


LOGGER = logging.getLogger(__name__)

PAVLOK_USER_URL = "https://api.pavlok.com/api/v5/user/"
PAVLOK_STIMULUS_URL = "https://api.pavlok.com/api/v5/stimulus/send"


def _normalize_token(value: str) -> str:
    """全角空白などを正規化し、Bearerを除いたASCIIトークン本体を返す。"""
    value = unicodedata.normalize("NFKC", value or "")
    value = re.sub(r"^bearer\s*", "", value.strip(), flags=re.IGNORECASE)
    value = "".join(value.split())

    if not value:
        return ""

    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(
            "PavlokトークンにASCII以外の文字が含まれています。"
        ) from exc

    return value


@dataclass(frozen=True)
class ZapResult:
    ok: bool
    status_code: int | None
    message: str
    runtime_token_refreshed: bool = False


class PavlokAuth:
    """
    config.ini の initial_token を使って /api/v5/user/ を呼び、
    レスポンスの user.token を実行用(runtime)トークンとして保持する。
    """

    def __init__(self, initial_token: str, timeout_seconds: float = 10.0):
        token = _normalize_token(initial_token)
        if not token:
            raise ValueError("Pavlok initial_token が空です。")

        self._initial_token = token
        self._runtime_token: str | None = None
        self._timeout_seconds = timeout_seconds
        self._lock = Lock()
        self._session = requests.Session()

    @staticmethod
    def _bearer(token: str) -> str:
        token = _normalize_token(token)
        if not token:
            raise ValueError("Pavlokトークンが空です。")
        return f"Bearer {token}"

    def refresh_runtime_token(self) -> bool:
        """初期トークンから runtime token を取得/更新する。"""
        LOGGER.info("[PAVLOK AUTH] 実行トークン取得中...")

        try:
            response = self._session.get(
                PAVLOK_USER_URL,
                headers={
                    "Authorization": self._bearer(self._initial_token),
                    "Accept": "application/json",
                },
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as exc:
            LOGGER.error("[PAVLOK AUTH] 接続エラー: %s", exc)
            return False

        if not response.ok:
            body = response.text.strip().replace("\n", " ")[:300]
            LOGGER.error(
                "[PAVLOK AUTH] HTTP %s%s",
                response.status_code,
                f" / {body}" if body else "",
            )
            return False

        try:
            data = response.json()
        except ValueError:
            LOGGER.error("[PAVLOK AUTH] JSON以外の応答が返りました。")
            return False

        user = data.get("user")
        if not isinstance(user, dict):
            LOGGER.error("[PAVLOK AUTH] レスポンスに user がありません。")
            return False

        runtime_token = user.get("token")
        if not isinstance(runtime_token, str) or not runtime_token.strip():
            LOGGER.error("[PAVLOK AUTH] レスポンスに user.token がありません。")
            return False

        runtime_token = _normalize_token(runtime_token)

        with self._lock:
            self._runtime_token = runtime_token

        LOGGER.info("[PAVLOK AUTH] 実行トークン取得 OK")
        return True

    def get_runtime_token(self) -> str:
        with self._lock:
            token = self._runtime_token
        if not token:
            raise RuntimeError("Pavlok runtime token が未取得です。")
        return token

    def get_current_user_for_test(self) -> dict:
        """テスト表示用。runtime token取得後の /user/ 応答を返す。"""
        token = self.get_runtime_token()
        response = self._session.get(
            PAVLOK_USER_URL,
            headers={
                "Authorization": self._bearer(token),
                "Accept": "application/json",
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return response.json()


class PavlokClient:
    def __init__(self, auth: PavlokAuth, timeout_seconds: float = 10.0):
        self.auth = auth
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def send_zap(self, output: int) -> ZapResult:
        """
        Zapを1回送信する。

        再送は行わない。
        401/403の場合のみ、そのZapを失敗扱いにした後 runtime token を更新し、
        次の予約から新しいトークンを使用する。
        """
        if not 1 <= output <= 100:
            return ZapResult(False, None, f"出力値が範囲外です: {output}")

        try:
            token = self.auth.get_runtime_token()
        except RuntimeError as exc:
            return ZapResult(False, None, str(exc))

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        payload = {
            "stimulus": {
                "stimulusType": "zap",
                "stimulusValue": output,
            }
        }

        try:
            response = self.session.post(
                PAVLOK_STIMULUS_URL,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            # タイムアウト等は「届いていない」と断定できないため再送しない。
            return ZapResult(False, None, f"通信エラー: {exc}")

        if response.ok:
            return ZapResult(True, response.status_code, "OK")

        body = response.text.strip().replace("\n", " ")[:300]
        message = f"HTTP {response.status_code}"
        if body:
            message += f" / {body}"

        refreshed = False
        if response.status_code in (401, 403):
            # 現在のZapは再送しない。次回用だけ更新する。
            refreshed = self.auth.refresh_runtime_token()

        return ZapResult(
            False,
            response.status_code,
            message,
            runtime_token_refreshed=refreshed,
        )
