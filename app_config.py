from __future__ import annotations

import configparser
import math
import sys
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


PAVLOK_MIN_OUTPUT = 1
PAVLOK_MAX_OUTPUT = 100


@dataclass(frozen=True)
class OutputGroup:
    name: str
    amounts: frozenset[int]
    output_mode: str
    fixed_output: int
    random_min: int
    random_max: int


@dataclass(frozen=True)
class Settings:
    youtube_api_key: str
    trigger_amounts: frozenset[int]

    pavlok_initial_token: str
    pavlok_enabled: bool
    delay_seconds: float
    cooldown_seconds: float

    output_mode: str
    fixed_output: int
    random_min: int
    random_max: int

    ignore_initial_history: bool
    output_groups: tuple[OutputGroup, ...] = ()

    def group_for_amount(self, amount: int) -> OutputGroup | None:
        return next((group for group in self.output_groups if amount in group.amounts), None)


def get_app_dir() -> Path:
    """Python実行時はソース位置、EXE化後はEXE位置を返す。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_config_path() -> Path:
    return get_app_dir() / "config.ini"


def _normalize_bearer_token(value: str) -> str:
    """Bearer付き/無し、全角空白などを吸収してASCIIトークン本体を返す。"""
    value = unicodedata.normalize("NFKC", value or "")
    value = re.sub(r"^bearer\s*", "", value.strip(), flags=re.IGNORECASE)
    # JWT/APIトークンに空白は不要。全角/改行/タブ等の混入も除去する。
    value = "".join(value.split())

    if not value:
        return ""

    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(
            "Pavlok initial_token にASCII以外の文字が含まれています。"
            "Bearer とトークンの間の全角文字などを確認してください。"
        ) from exc

    return value


def _normalize_ascii_compact(value: str, label: str) -> str:
    """全角空白・半角空白・改行・タブを除去しASCII文字列として返す。"""
    value = unicodedata.normalize("NFKC", value or "")
    value = "".join(value.split())

    if not value:
        return ""

    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(
            f"{label} にASCII以外の文字が含まれています。"
            "全角文字やコピー時の余計な文字を確認してください。"
        ) from exc

    return value


def _looks_like_placeholder(value: str) -> bool:
    upper = value.upper()
    return not value or "PASTE_" in upper or "YOUR_" in upper or "ここに" in value


def _load_output_groups(parser: configparser.ConfigParser) -> tuple[OutputGroup, ...]:
    names = [f"SuperChat{i}" for i in range(1, 5)]
    if not any(parser.has_section(name) for name in names):
        return ()
    groups = []
    used = set()
    for name in names:
        if not parser.has_section(name):
            raise ValueError(f"4グループ設定には [{name}] が必要です。")
        try:
            # 無効グループは金額・出力の検証や重複判定にも参加しない。
            if not parser.getboolean(name, "enabled", fallback=True):
                continue
            amounts = frozenset(int(x.strip()) for x in parser.get(name, "amounts").split(",") if x.strip())
            mode = parser.get(name, "output_mode").strip().lower()
            fixed = parser.getint(name, "fixed_output", fallback=20)
            low = parser.getint(name, "random_min", fallback=20)
            high = parser.getint(name, "random_max", fallback=20)
            # 使用する出力値は明示必須。入力漏れで意図しない強さを送らない。
            required = ("fixed_output",) if mode == "fixed" else ("random_min", "random_max")
            if any(not parser.has_option(name, key) for key in required):
                raise ValueError("使用する出力値を指定してください。")
        except (ValueError, configparser.Error) as exc:
            raise ValueError(f"[{name}] 設定が不正です: {exc}") from exc
        if not amounts or any(amount <= 0 for amount in amounts):
            raise ValueError(f"[{name}] amounts は1以上の整数を指定してください。")
        if used.intersection(amounts):
            raise ValueError(f"[{name}] amounts が他グループと重複しています。")
        if mode not in {"fixed", "random"}:
            raise ValueError(f"[{name}] output_mode は fixed または random を指定してください。")
        if any(not 1 <= value <= 100 for value in (fixed, low, high)) or low > high:
            raise ValueError(f"[{name}] 出力は1～100、random_min <= random_max にしてください。")
        used.update(amounts)
        groups.append(OutputGroup(name, amounts, mode, fixed, low, high))
    if not groups:
        raise ValueError("少なくとも1つのSuperChatグループをenabled=trueにしてください。")
    return tuple(groups)


def load_settings(*, require_youtube_key: bool = True) -> Settings:
    config_path = get_config_path()

    if not config_path.exists():
        raise FileNotFoundError(
            f"config.ini がありません: {config_path}"
        )

    parser = configparser.ConfigParser()
    read_files = parser.read(config_path, encoding="utf-8-sig")
    if not read_files:
        raise RuntimeError("config.ini を読み込めませんでした。")

    youtube_api_key = _normalize_ascii_compact(
        parser.get("YouTube", "api_key", fallback=""),
        "YouTube APIキー",
    )
    if require_youtube_key and _looks_like_placeholder(youtube_api_key):
        raise ValueError(
            "[YouTube] api_key が未設定です。config.ini を編集してください。"
        )

    output_groups = _load_output_groups(parser)
    raw_amounts = (
        ",".join(str(amount) for group in output_groups for amount in group.amounts)
        if output_groups else parser.get("SuperChat", "amounts", fallback="")
    )
    try:
        trigger_amounts = frozenset(
            int(x.strip())
            for x in raw_amounts.split(",")
            if x.strip()
        )
    except ValueError as exc:
        raise ValueError(
            "[SuperChat] amounts は整数をカンマ区切りで指定してください。"
        ) from exc

    if not trigger_amounts:
        raise ValueError("[SuperChat] amounts が空です。")
    if any(x <= 0 for x in trigger_amounts):
        raise ValueError("[SuperChat] amounts は1以上にしてください。")

    initial_token = _normalize_bearer_token(
        parser.get("Pavlok", "initial_token", fallback="")
    )
    pavlok_enabled = parser.getboolean("Pavlok", "enabled", fallback=False)

    if pavlok_enabled and _looks_like_placeholder(initial_token):
        raise ValueError(
            "[Pavlok] enabled=true ですが initial_token が未設定です。"
        )

    delay_seconds = parser.getfloat("Pavlok", "delay_seconds", fallback=0.0)
    cooldown_seconds = parser.getfloat("Pavlok", "cooldown_seconds", fallback=0.0)

    # getfloatはnan/infも受け入れる。予約の無限待機やcooldownの無効化を防ぐ。
    if not math.isfinite(delay_seconds) or delay_seconds < 0:
        raise ValueError("delay_seconds は0以上の有限の数値にしてください。")
    if not math.isfinite(cooldown_seconds) or cooldown_seconds < 0:
        raise ValueError("cooldown_seconds は0以上の有限の数値にしてください。")

    # グループ方式では旧共通出力を参照しない（不正な旧値も影響させない）。
    output_mode = "fixed" if output_groups else parser.get("Pavlok", "output_mode", fallback="fixed").strip().lower()
    if output_mode not in {"fixed", "random"}:
        raise ValueError("output_mode は fixed または random を指定してください。")

    fixed_output = 20 if output_groups else parser.getint("Pavlok", "fixed_output", fallback=20)
    random_min = 20 if output_groups else parser.getint("Pavlok", "random_min", fallback=20)
    random_max = 20 if output_groups else parser.getint("Pavlok", "random_max", fallback=20)

    for label, value in (
        ("fixed_output", fixed_output),
        ("random_min", random_min),
        ("random_max", random_max),
    ):
        if not PAVLOK_MIN_OUTPUT <= value <= PAVLOK_MAX_OUTPUT:
            raise ValueError(f"{label} は1～100で指定してください。")

    if random_min > random_max:
        raise ValueError("random_min は random_max 以下にしてください。")

    ignore_initial_history = parser.getboolean(
        "System", "ignore_initial_history", fallback=True
    )

    return Settings(
        youtube_api_key=youtube_api_key,
        trigger_amounts=trigger_amounts,
        pavlok_initial_token=initial_token,
        pavlok_enabled=pavlok_enabled,
        delay_seconds=delay_seconds,
        cooldown_seconds=cooldown_seconds,
        output_mode=output_mode,
        fixed_output=fixed_output,
        random_min=random_min,
        random_max=random_max,
        ignore_initial_history=ignore_initial_history,
        output_groups=output_groups,
    )


def ensure_pavlok_token_present(settings: Settings) -> None:
    if _looks_like_placeholder(settings.pavlok_initial_token):
        raise ValueError(
            "[Pavlok] initial_token が未設定です。config.ini を編集してください。"
        )
