# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules
import configparser
from pathlib import Path

# 利用者の認証情報を誤って配布用EXEへ同梱しない。
defaults = configparser.ConfigParser(interpolation=None)
defaults.read(Path(SPECPATH) / "config.defaults.ini", encoding="utf-8-sig")
for section, key in (("YouTube", "api_key"), ("Pavlok", "initial_token")):
    value = defaults.get(section, key, fallback="").strip()
    if value and not value.upper().startswith(("PASTE_", "YOUR_")):
        raise ValueError(f"config.defaults.ini の [{section}] {key} は空欄またはプレースホルダーにしてください。")

hiddenimports = (
    collect_submodules("grpc")
    + collect_submodules("google.protobuf")
)

a = Analysis(
    ["pavlok_superchat.py"],
    pathex=[],
    binaries=[],
    datas=[("config.defaults.ini", "."), ("VERSION.txt", ".")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PavlokSuperChat",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
