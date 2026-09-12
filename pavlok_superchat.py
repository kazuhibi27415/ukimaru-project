from __future__ import annotations

import logging
import sys
from decimal import Decimal

from app_config import load_settings
from pavlok_api import PavlokAuth, PavlokClient
from trigger_worker import TriggerWorker
from youtube_stream import SuperChatEvent, extract_video_id, get_live_chat_id, watch_live_chat


LOG_FORMAT = "[%(asctime)s] %(message)s"
DATE_FORMAT = "%H:%M:%S"


def configure_stdio() -> None:
    """EXEでは環境変数が反映されない場合もあるため、GUI用パイプを明示設定する。"""
    if sys.platform == "win32" and "--console" in sys.argv and sys.stdout is None:
        import ctypes
        import os
        import msvcrt
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetStdHandle.argtypes = [ctypes.c_ulong]
        kernel.GetStdHandle.restype = ctypes.c_void_p
        if "--gui-worker" not in sys.argv:
            # 明示的なCLI起動だけコンソールへ接続する。GUIと監視子プロセスは表示しない。
            if not kernel.AttachConsole(ctypes.c_ulong(-1)):
                kernel.AllocConsole()
        for name, number, mode, flags in (("stdin", -10, "r", os.O_RDONLY),
                                          ("stdout", -11, "w", os.O_WRONLY),
                                          ("stderr", -12, "w", os.O_WRONLY)):
            if getattr(sys, name) is None:
                handle = kernel.GetStdHandle(ctypes.c_ulong(number))
                if handle and handle != ctypes.c_void_p(-1).value:
                    descriptor = msvcrt.open_osfhandle(handle, flags | os.O_BINARY)
                    setattr(sys, name, open(descriptor, mode, encoding="utf-8", errors="replace", buffering=1))
    if "--gui-worker" in sys.argv:
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        if sys.stdout is not None:
            sys.stdout.reconfigure(line_buffering=True)
    else:
        # 通常コンソールは既存の文字コードを保ち、表示不能な文字で停止させない。
        for stream in (sys.stdout, sys.stderr):
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="replace")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
    )


def main() -> int:
    configure_logging()
    log = logging.getLogger("main")

    print()
    print("====================================================")
    print(" YouTube SuperChat -> Pavlok Controller  v0.3.0")
    print("====================================================")
    print()

    settings = load_settings(require_youtube_key=True)

    print("設定読み込み OK")
    print("対象: Super Chatのみ / JPY固定 / 金額完全一致")
    print(
        "対象金額:",
        ", ".join(f"¥{x:,}" for x in sorted(settings.trigger_amounts)),
    )
    print(f"Pavlok: {'ON (実送信)' if settings.pavlok_enabled else 'OFF (DRY-RUN)'}")
    print(f"Delay: {settings.delay_seconds:g}s")
    print(f"Cooldown: {settings.cooldown_seconds:g}s")
    if settings.output_groups:
        for group in settings.output_groups:
            amounts = ", ".join(f"¥{amount:,}" for amount in sorted(group.amounts))
            output = (f"fixed {group.fixed_output}" if group.output_mode == "fixed"
                      else f"random {group.random_min}-{group.random_max}")
            print(f"{group.name}: {amounts} -> {output}")
    elif settings.output_mode == "fixed":
        print(f"Output: fixed {settings.fixed_output}")
    else:
        print(f"Output: random {settings.random_min}-{settings.random_max}")
    print()

    pavlok_client: PavlokClient | None = None

    if settings.pavlok_enabled:
        auth = PavlokAuth(settings.pavlok_initial_token)
        if not auth.refresh_runtime_token():
            raise RuntimeError(
                "Pavlok runtime token を取得できませんでした。初期トークンを確認してください。"
            )
        pavlok_client = PavlokClient(auth)
    else:
        log.info("[PAVLOK] DRY-RUN: 実機へのZap送信は無効です。")

    value = input("YouTube Live URL / Video ID: ").strip()
    video_id = extract_video_id(value)
    log.info("Video ID: %s", video_id)

    log.info("Live Chat ID取得中...")
    live_chat_id = get_live_chat_id(video_id, settings.youtube_api_key)
    log.info("Live Chat ID: %s", live_chat_id)

    worker = TriggerWorker(settings, pavlok_client)

    def on_superchat(event: SuperChatEvent) -> None:
        log.info(
            "[SUPERCHAT] %s %s / %s",
            event.author,
            event.amount_display,
            event.currency,
        )

        # 仕様: JPY固定
        if event.currency != "JPY":
            log.info("[SKIP] JPY以外のため対象外")
            return

        # 仕様: 円単位の完全一致
        if event.amount != event.amount.to_integral_value():
            log.info("[SKIP] 整数円でないため対象外")
            return

        amount_yen = int(event.amount)
        if amount_yen not in settings.trigger_amounts:
            log.info("[SKIP] %s は発火対象外", event.amount_display)
            return

        log.info("[MATCH] %s 発火対象", event.amount_display)
        worker.enqueue(event)

    try:
        watch_live_chat(
            live_chat_id=live_chat_id,
            api_key=settings.youtube_api_key,
            ignore_initial_history=settings.ignore_initial_history,
            on_superchat=on_superchat,
        )
    except KeyboardInterrupt:
        print()
        log.info("監視を停止します。")
    finally:
        worker.stop()

    return 0


if __name__ == "__main__":
    configure_stdio()
    try:
        if "--console" in sys.argv:
            raise SystemExit(main())
        else:
            from settings_ui import run_gui
            run_gui()
    except Exception as exc:
        configure_logging()
        logging.getLogger("main").error("[FATAL] %s", exc)
        print()
        input("Enterキーで終了...")
        raise SystemExit(1)
