"""YouTube専用OAuth。認証情報はWindowsのユーザー単位で暗号化して保存する。"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from windows_dpapi import protect

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
LOGGER = logging.getLogger(__name__)


def app_data_dir() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return local / "PavlokSuperChat"


def token_path() -> Path:
    return app_data_dir() / "youtube_oauth.bin"


def managed_client_path() -> Path:
    return app_data_dir() / "youtube_oauth_client.json"


def _client_config(data) -> dict:
    try:
        installed = data["installed"]
        client_id = installed["client_id"]
        client_secret = installed["client_secret"]
        if not isinstance(client_id, str) or not client_id or not isinstance(client_secret, str) or not client_secret:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError("デスクトップアプリ用のOAuthクライアントJSONを選択してください。") from None
    # 利用者が選択したJSONから任意の接続先や余分なデータを引き継がない。
    return {"installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": TOKEN_URI,
        "redirect_uris": ["http://localhost"],
    }}


def _write_managed_client(client: dict) -> str:
    path = managed_client_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, prefix="youtube-client-", suffix=".tmp",
                                         delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(client, handle, ensure_ascii=True, separators=(",", ":"))
            handle.write("\n")
        os.replace(temporary, path)
    except OSError:
        raise RuntimeError("OAuthクライアントJSONをアプリ管理フォルダへ保存できませんでした。") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(path)


def install_client_file(source: str | Path) -> str:
    try:
        data = json.loads(Path(source).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        raise ValueError("デスクトップアプリ用のOAuthクライアントJSONを選択してください。") from None
    return _write_managed_client(_client_config(data))


def recover_client_from_login() -> str | None:
    """元JSONが消えていても、暗号化済みログインに必要なクライアント情報があれば復元する。"""
    try:
        if not token_path().exists():
            return None
        credentials = json.loads(protect(token_path().read_bytes(), decrypt=True))
        client = _client_config({"installed": credentials})
        return _write_managed_client(client)
    except (OSError, ValueError, RuntimeError, TypeError):
        return None


def ensure_managed_client(configured: str) -> str:
    source = Path(configured) if configured else None
    managed = managed_client_path()
    if source is not None and source.is_file():
        try:
            if source.resolve() == managed.resolve():
                _client_config(json.loads(source.read_text(encoding="utf-8-sig")))
                return str(managed)
        except (OSError, ValueError, TypeError):
            pass
        return install_client_file(source)
    if managed.is_file():
        try:
            _client_config(json.loads(managed.read_text(encoding="utf-8-sig")))
            return str(managed)
        except (OSError, ValueError, TypeError):
            pass
    return recover_client_from_login() or configured


def forget_login() -> None:
    token_path().unlink(missing_ok=True)


class YouTubeOAuth:
    def __init__(self, client_file: str):
        self.credentials = None
        try:
            self.client = _client_config(json.loads(Path(client_file).read_text(encoding="utf-8-sig")))
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
