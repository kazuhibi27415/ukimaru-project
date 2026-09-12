from __future__ import annotations

import logging
import time
from dataclasses import replace
from decimal import Decimal

from app_config import load_settings
from trigger_worker import TriggerWorker
from youtube_stream import SuperChatEvent


def event(number: int, amount: int) -> SuperChatEvent:
    return SuperChatEvent(
        message_id=f"LOCAL-TEST-{number}",
        author=f"QueueTest{number}",
        amount=Decimal(amount),
        amount_micros=amount * 1_000_000,
        amount_display=f"¥{amount:,}",
        currency="JPY",
        comment="local queue test",
        tier=1,
        published_at="LOCAL",
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
    base = load_settings(require_youtube_key=False)
    settings = replace(
        base,
        pavlok_enabled=False,
        delay_seconds=0.3,
        cooldown_seconds=0.7,
        output_mode="fixed",
        fixed_output=1,
    )

    worker = TriggerWorker(settings, None)
    try:
        worker.enqueue(event(1, 500))
        worker.enqueue(event(2, 1000))
        worker.enqueue(event(3, 3000))
        worker.jobs.join()
        print()
        print("QUEUE TEST OK: 3件をFIFOでDRY-RUN処理しました。")
    finally:
        worker.stop()
        time.sleep(0.1)


if __name__ == "__main__":
    main()
