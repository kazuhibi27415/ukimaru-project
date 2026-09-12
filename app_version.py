"""ソース実行とEXEで共通のバージョン表示。"""
from pathlib import Path

VERSION = Path(__file__).with_name("VERSION.txt").read_text(encoding="utf-8-sig").strip()
