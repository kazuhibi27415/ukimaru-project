from __future__ import annotations

import logging

from app_config import ensure_pavlok_token_present, load_settings
from pavlok_api import PavlokAuth


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    settings = load_settings(require_youtube_key=False)
    ensure_pavlok_token_present(settings)

    auth = PavlokAuth(settings.pavlok_initial_token)
    if not auth.refresh_runtime_token():
        print("\nPavlok認証テスト: NG")
        return 1

    try:
        data = auth.get_current_user_for_test()
    except Exception as exc:
        print(f"\nPavlok runtime token確認: NG ({exc})")
        return 1

    user = data.get("user", {}) if isinstance(data, dict) else {}
    user_id = user.get("id", "?")
    username = user.get("username") or "(未設定)"

    print()
    print("========================================")
    print(" Pavlok認証テスト: OK")
    print("========================================")
    print(f"User ID : {user_id}")
    print(f"Username: {username}")
    print("Runtime token: 取得OK（値は表示しません）")
    print("Zapは送信していません。")
    print("========================================")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:
        print(f"\nERROR: {exc}")
        code = 1
    input("\nEnterキーで終了...")
    raise SystemExit(code)
