"""Pavlok初期トークンをconfig.iniから分離して暗号化保存する。"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

from windows_dpapi import protect


def token_path() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return local / "PavlokSuperChat" / "pavlok_initial_token.bin"


def load_token() -> str:
    path = token_path()
    if not path.exists():
        return ""
    try:
        return protect(path.read_bytes(), decrypt=True).decode("ascii")
    except (OSError, UnicodeError):
        raise RuntimeError(
            "保存済みPavlokトークンを読み込めません。"
            f"再設定する場合は {path} を削除してから起動してください。"
        ) from None


def save_token(token: str) -> None:
    path = token_path()
    if not token:
        path.unlink(missing_ok=True)
        return
    try:
        data = protect(token.encode("ascii"))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix="pavlok-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    except (OSError, UnicodeError):
        raise RuntimeError("PavlokトークンをWindowsで暗号化保存できませんでした。") from None
