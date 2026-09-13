"""YouTube専用OAuth。認証情報はWindowsのユーザー単位で暗号化して保存する。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path
import tempfile

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
LOGGER = logging.getLogger(__name__)


def token_path() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return local / "PavlokSuperChat" / "youtube_oauth.bin"


def forget_login() -> None:
    token_path().unlink(missing_ok=True)


def protect(data: bytes, *, decrypt: bool = False) -> bytes:
    """DPAPIのUIを禁止し、平文保存へフォールバックしない。"""
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    result = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise OSError("Googleログイン情報の暗号化・復号に失敗しました。")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


class YouTubeOAuth:
    def __init__(self, client_file: str):
        self.credentials = None
        try:
            data = json.loads(Path(client_file).read_text(encoding="utf-8-sig"))["installed"]
            if not data.get("client_id") or not data.get("client_secret"):
                raise ValueError()
            # 選択ファイル内の任意URLに認証情報を送信しない。
            self.client = {"installed": {
                "client_id": data["client_id"], "client_secret": data["client_secret"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": TOKEN_URI,
                "redirect_uris": ["http://localhost"],
            }}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise ValueError("デスクトップアプリ用のOAuthクライアントJSONを選択してください。") from None

    def _save(self):
        data = protect(self.credentials.to_json().encode("utf-8"))
        path = token_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix="oauth-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def login(self):
        try:
            if token_path().exists():
                data = json.loads(protect(token_path().read_bytes(), decrypt=True))
                if data.get("client_id") == self.client["installed"]["client_id"]:
                    data["token_uri"] = TOKEN_URI
                    self.credentials = Credentials.from_authorized_user_info(data, SCOPES)
                    self.get_access_token()
                    return
        except Exception:
            self.credentials = None
            # 破損・失効時はユーザー操作で再ログイン。一切トークンをログに出さない。
            LOGGER.info("[AUTH] 保存済みGoogleログインを利用できません。再ログインします。")
        LOGGER.info("[AUTH] ブラウザで配信者のGoogleアカウントへログインしてください（待機3分）。")
        flow_logger = logging.getLogger("google_auth_oauthlib.flow")
        was_disabled = flow_logger.disabled
        # ライブラリのHTTPアクセスログには認可コード付きURLが含まれる。
        flow_logger.disabled = True
        try:
            flow = InstalledAppFlow.from_client_config(self.client, SCOPES, autogenerate_code_verifier=True)
            self.credentials = flow.run_local_server(
                host="127.0.0.1", port=0, timeout_seconds=180,
                authorization_prompt_message="", prompt="consent", access_type="offline",
                success_message="Login completed. You may close this window.",
            )
            if not self.credentials or not self.credentials.valid or not self.credentials.refresh_token:
                raise ValueError()
            self._save()
        except Exception:
            self.credentials = None
            raise RuntimeError("Googleログインに失敗しました。許可・テストユーザー設定を確認して再度開始してください。") from None
        finally:
            flow_logger.disabled = was_disabled
        LOGGER.info("[AUTH] Googleログイン完了")

    def get_access_token(self, force_refresh=False) -> str:
        if self.credentials is None:
            raise RuntimeError("Googleログインが必要です。監視を開始し直してください。")
        try:
            if force_refresh or not self.credentials.valid:
                self.credentials.refresh(Request())
                self._save()
            if not self.credentials.token:
                raise ValueError()
            return self.credentials.token
        except Exception:
            raise RuntimeError("Google認証の更新に失敗しました。ログインを解除して監視を開始し直してください。") from None
