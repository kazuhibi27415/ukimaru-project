from __future__ import annotations

import itertools
import logging
import queue
import random
import threading
import time
from dataclasses import dataclass
from decimal import Decimal

from app_config import OutputGroup, Settings
from pavlok_api import PavlokClient
from youtube_stream import SuperChatEvent


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TriggerJob:
    number: int
    message_id: str
    author: str
    amount: Decimal
    amount_display: str
    ready_at: float
    output_group: OutputGroup | None = None


class TriggerWorker:
    """FIFOキューで delay と cooldown を守りながらZap予約を処理する。"""

    def __init__(self, settings: Settings, pavlok_client: PavlokClient | None):
        self.settings = settings
        self.pavlok_client = pavlok_client
        self.jobs: queue.Queue[TriggerJob] = queue.Queue()
        self.stop_event = threading.Event()
        self.counter = itertools.count(1)
        self.last_attempt_at: float | None = None

        self.thread = threading.Thread(
            target=self._run,
            name="PavlokTriggerWorker",
            daemon=True,
        )
        self.thread.start()

    def enqueue(self, event: SuperChatEvent) -> None:
        group = self.settings.group_for_amount(event.amount)
        if self.settings.output_groups and group is None:
            raise ValueError("対象金額に対応する出力グループがありません。")
        number = next(self.counter)
        job = TriggerJob(
            number=number,
            message_id=event.message_id,
            author=event.author,
            amount=event.amount,
            amount_display=event.amount_display,
            ready_at=time.monotonic() + self.settings.delay_seconds,
            output_group=group,
        )
        self.jobs.put(job)
        LOGGER.info(
            "[QUEUE] #%d %s / %s 予約 (delay=%gs)",
            job.number,
            job.amount_display,
            job.author,
            self.settings.delay_seconds,
        )

    def stop(self) -> None:
        # 未実行キューは永続化しない。終了時に破棄する。
        self.stop_event.set()

    def _select_output(self, group: OutputGroup | None = None) -> int:
        profile = group or self.settings
        if profile.output_mode == "fixed":
            return profile.fixed_output
        return random.randint(profile.random_min, profile.random_max)

    def _wait_until(self, target: float) -> bool:
        while not self.stop_event.is_set():
            remaining = target - time.monotonic()
            if remaining <= 0:
                return True
            self.stop_event.wait(min(remaining, 0.5))
        return False

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                job = self.jobs.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                if not self._wait_until(job.ready_at):
                    return

                if self.last_attempt_at is not None and self.settings.cooldown_seconds > 0:
                    next_allowed = self.last_attempt_at + self.settings.cooldown_seconds
                    remaining = next_allowed - time.monotonic()
                    if remaining > 0:
                        LOGGER.info(
                            "[COOLDOWN] #%d あと %.1fs 待機",
                            job.number,
                            remaining,
                        )
                        if not self._wait_until(next_allowed):
                            return

                profile = job.output_group or self.settings
                if job.output_group:
                    LOGGER.info("[GROUP] #%d %s", job.number, job.output_group.name)
                output = self._select_output(job.output_group)
                if profile.output_mode == "random":
                    LOGGER.info(
                        "[OUTPUT] #%d random %d-%d => %d",
                        job.number,
                        profile.random_min,
                        profile.random_max,
                        output,
                    )
                else:
                    LOGGER.info("[OUTPUT] #%d fixed => %d", job.number, output)

                # dry-runでも実運用と同じcooldown挙動を再現する。
                self.last_attempt_at = time.monotonic()

                if not self.settings.pavlok_enabled:
                    LOGGER.info(
                        "[DRY-RUN] #%d zap output=%d（Pavlokには送信していません）",
                        job.number,
                        output,
                    )
                    continue

                if self.pavlok_client is None:
                    LOGGER.error("[PAVLOK] #%d クライアント未初期化", job.number)
                    continue

                LOGGER.info("[PAVLOK] #%d zap output=%d 送信", job.number, output)
                result = self.pavlok_client.send_zap(output)

                if result.ok:
                    LOGGER.info(
                        "[PAVLOK] #%d OK (HTTP %s)",
                        job.number,
                        result.status_code,
                    )
                else:
                    LOGGER.error("[PAVLOK] #%d ERROR: %s", job.number, result.message)
                    LOGGER.error("[PAVLOK] #%d 再送しません。", job.number)
                    if result.runtime_token_refreshed:
                        LOGGER.info(
                            "[PAVLOK AUTH] runtime token更新済み。次の予約から使用します。"
                        )

            except Exception:
                LOGGER.exception("[WORKER ERROR] #%d", job.number)
            finally:
                self.jobs.task_done()
