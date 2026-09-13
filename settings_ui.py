"""設定画面と監視プロセスの開始・停止。API処理は既存コンソールへ委譲する。"""
from __future__ import annotations

import configparser
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from app_config import ensure_config_exists, settings_from_parser
from app_version import VERSION
from youtube_stream import extract_video_id

OUTPUT_LABELS = {"fixed": "固定", "random": "ランダム"}
OUTPUT_VALUES = {label: value for value, label in OUTPUT_LABELS.items()}
AUTH_LABELS = {"api_key": "APIキー（公開配信）", "oauth": "Googleログイン（メン限向け）"}
AUTH_VALUES = {label: value for value, label in AUTH_LABELS.items()}


def clipboard_action(widget, action):
    """入力欄と読み取り専用ログで同じ操作を提供する。"""
    editable = str(widget.cget("state")) == "normal"
    is_text = isinstance(widget, tk.Text)
    try:
        if action == "select_all":
            if is_text:
                widget.tag_add("sel", "1.0", "end-1c")
            else:
                widget.selection_range(0, "end")
            return "break"
        if action in ("copy", "cut"):
            if action == "cut" and not editable:
                return "break"
            if is_text:
                value = widget.get("sel.first", "sel.last")
            else:
                value = widget.get()[widget.index("sel.first"):widget.index("sel.last")]
            widget.clipboard_clear()
            widget.clipboard_append(value)
            if action == "cut":
                widget.delete("sel.first", "sel.last")
        elif action == "paste" and editable:
            value = widget.clipboard_get()
            if not is_text:
                value = value.replace("\r", "").replace("\n", "")
            try:
                widget.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            widget.insert("insert", value)
    except tk.TclError:
        # 選択なし・クリップボードが空・画像のみの場合も画面を停止させない。
        pass
    return "break"


def add_clipboard_menu(widget):
    menu = tk.Menu(widget, tearoff=False)
    for label, action in (("切り取り", "cut"), ("コピー", "copy"),
                          ("貼り付け", "paste"), ("すべて選択", "select_all")):
        menu.add_command(label=label, command=lambda action=action: clipboard_action(widget, action))

    def popup(event):
        widget.focus_set()
        editable = str(widget.cget("state")) == "normal"
        menu.entryconfigure(0, state="normal" if editable else "disabled")
        menu.entryconfigure(2, state="normal" if editable else "disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    widget.bind("<Button-3>", popup)
    for event, action in (("<<Copy>>", "copy"), ("<<Cut>>", "cut"), ("<<Paste>>", "paste"),
                          ("<Control-a>", "select_all"), ("<Control-A>", "select_all")):
        widget.bind(event, lambda event, action=action: clipboard_action(widget, action))

def save_config(parser: configparser.ConfigParser, path: Path) -> None:
    """検証してから同じフォルダ内で置換し、書き込み途中の設定を残さない。"""
    settings_from_parser(parser, require_youtube_key=False)
    # 元の説明コメントを保持し、画面の設定値だけ更新する。
    original = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    remaining = {section: dict(parser[section]) for section in parser.sections()}
    lines = []
    section = None
    for line in original.splitlines():
        match = re.match(r"\s*\[([^]]+)\]", line)
        if match:
            if section in remaining:
                lines.extend(f"{key}={value}" for key, value in remaining.pop(section).items())
            section = match.group(1)
        elif section in remaining and "=" in line and not line.lstrip().startswith((";", "#")):
            key = line.split("=", 1)[0].strip().lower()
            if key in remaining[section]:
                line = f"{key}={remaining[section].pop(key)}"
        lines.append(line)
    if section in remaining:
        lines.extend(f"{key}={value}" for key, value in remaining.pop(section).items())
    for section, values in remaining.items():
        lines.extend(["", f"[{section}]", *(f"{key}={value}" for key, value in values.items())])
    text = "\n".join(lines).rstrip() + "\n"
    check = configparser.ConfigParser(interpolation=None)
    check.read_string(text)
    settings_from_parser(check, require_youtube_key=False)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="\r\n",
                                         dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


class MonitorProcess:
    """1つの監視だけを実行。終了確認までは新しい監視を起動しない。"""

    def __init__(self):
        self.process = None
        self.reader = None
        self.messages = queue.Queue(maxsize=2000)

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    def start(self, video_id: str):
        if self.running or (self.reader is not None and self.reader.is_alive()):
            raise RuntimeError("前の監視が終了するまでお待ちください。")
        while not self.messages.empty():
            self.messages.get_nowait()
        command = ([sys.executable, "--console", "--gui-worker"] if getattr(sys, "frozen", False) else
                   [sys.executable, "-u", str(Path(__file__).with_name("pavlok_superchat.py")), "--console", "--gui-worker"])
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        process = self.process
        try:
            process.stdin.write(video_id + "\n")
            process.stdin.close()
        except (OSError, BrokenPipeError):
            self.stop()
            raise
        self.reader = threading.Thread(target=self._read, args=(process,), daemon=True)
        self.reader.start()

    def _read(self, process):
        try:
            for line in process.stdout:
                try:
                    self.messages.put_nowait(line)
                except queue.Full:
                    # 画面ログが詰まっても監視プロセスを止めない。
                    pass
        finally:
            process.stdout.close()

    def stop(self):
        if self.running:
            # 専用プロセスごと終了し、gRPC待ちと未送信キューを破棄する。
            try:
                self.process.terminate()
            except OSError:
                if self.running:
                    raise


class SettingsWindow:
    def __init__(self, root):
        self.root = root
        self.monitor = MonitorProcess()
        self.closing = False
        self.was_running = False
        self.stop_requested = False
        self.secrets = []
        self.fields = {}
        self.controls = []
        self.path = ensure_config_exists()
        self.parser = configparser.ConfigParser(interpolation=None)
        if self.path.exists():
            self.parser.read(self.path, encoding="utf-8-sig")
        root.title(f"PavlokSuperChat v{VERSION} — 設定と監視")
        root.geometry("1000x780")
        root.minsize(900, 700)
        root.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(root, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"PavlokSuperChat v{VERSION}", font=("Yu Gothic UI", 18, "bold")).pack(anchor="w")
        ttk.Label(frame, text="日本円のSuper Chatを金額完全一致で検出します。設定は開始前に保存されます。").pack(anchor="w")
        ttk.Label(frame, text=f"設定の保存先: {self.path}", foreground="#666666").pack(anchor="w")
        general = ttk.LabelFrame(frame, text="認証と共通設定", padding=10)
        general.pack(fill="x", pady=8)
        general.columnconfigure(1, weight=1)
        self.entry(general, 0, "YouTube APIキー", "YouTube", "api_key", "", secret=True)
        self.entry(general, 1, "Pavlok初期トークン", "Pavlok", "initial_token", "", secret=True)
        row = ttk.Frame(general)
        row.grid(row=2, column=0, columnspan=2, sticky="w", pady=6)
        self.check(row, "実機へZapを送信（OFFはDRY-RUN）", "Pavlok", "enabled", "false")
        self.check(row, "起動時の履歴を無視", "System", "ignore_initial_history", "true")
        self.entry(general, 3, "検出後の待機秒数", "Pavlok", "delay_seconds", "5", width=12)
        self.entry(general, 4, "共通クールダウン秒数", "Pavlok", "cooldown_seconds", "10", width=12)
        ttk.Label(general, text="YouTube認証方式").grid(row=5, column=0, sticky="w")
        auth_bar = ttk.Frame(general)
        auth_bar.grid(row=5, column=1, sticky="ew")
        mode = ttk.Combobox(auth_bar, textvariable=self.var("YouTube", "auth_mode", "api_key"),
                            values=tuple(AUTH_VALUES), state="readonly", width=32)
        mode.pack(side="left")
        logout = ttk.Button(auth_bar, text="Googleログインを解除", command=self.forget_google_login)
        logout.pack(side="left", padx=8)
        self.controls.extend((mode, logout))
        self.entry(general, 6, "OAuthクライアントJSON", "YouTube", "oauth_client_file", "")
        browse = ttk.Button(general, text="JSONを選択", command=self.choose_oauth_client)
        browse.grid(row=6, column=2, padx=5)
        self.controls.append(browse)
        groups = ttk.LabelFrame(frame, text="金額グループ — 使わないグループはOFF（最低1つON）", padding=8)
        groups.pack(fill="x")
        for column, label in enumerate(("使用", "対象金額（円・カンマ区切り）", "出力方法", "固定値", "ランダム下限", "ランダム上限")):
            ttk.Label(groups, text=label).grid(row=0, column=column, padx=5, sticky="w")
        # 旧形式は1グループにまとめ、既存の金額と出力をそのまま引き継ぐ。
        legacy = not any(self.parser.has_section(f"SuperChat{i}") for i in range(1, 5))
        for i in range(1, 5):
            section = f"SuperChat{i}"
            if legacy:
                self.parser[section] = {
                    "enabled": "true" if i == 1 else "false",
                    "amounts": self.parser.get("SuperChat", "amounts", fallback="200,500,1000") if i == 1 else "",
                    **{key: self.parser.get("Pavlok", key, fallback=default) for key, default in
                       (("output_mode", "fixed"), ("fixed_output", "20"), ("random_min", "20"), ("random_max", "20"))},
                }
            enabled = self.var(section, "enabled", "true")
            control = ttk.Checkbutton(groups, text=f"{i}", variable=enabled, onvalue="true", offvalue="false")
            control.grid(row=i, column=0, padx=5, pady=5)
            self.controls.append(control)
            for col, (key, default, width) in enumerate((("amounts", "", 30), ("output_mode", "fixed", 9),
                    ("fixed_output", "20", 9), ("random_min", "20", 9), ("random_max", "20", 9)), 1):
                variable = self.var(section, key, default)
                control = (ttk.Combobox(groups, textvariable=variable, values=tuple(OUTPUT_VALUES), width=width, state="readonly")
                           if key == "output_mode" else ttk.Entry(groups, textvariable=variable, width=width))
                control.grid(row=i, column=col, padx=5, pady=5, sticky="ew")
                self.controls.append(control)
        ttk.Label(frame, text="固定＝固定値、ランダム＝下限～上限から抽選。出力は1～100。金額のグループ間重複は不可。").pack(anchor="w", pady=5)
        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=6)
        ttk.Label(bar, text="配信URL / 動画ID").pack(side="left")
        self.video = tk.StringVar()
        self.video_entry = ttk.Entry(bar, textvariable=self.video)
        self.video_entry.pack(side="left", fill="x", expand=True, padx=8)
        self.controls.append(self.video_entry)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        self.save_button = ttk.Button(buttons, text="設定を保存", command=self.save)
        self.save_button.pack(side="left")
        self.start_button = ttk.Button(buttons, text="監視開始", command=self.start)
        self.start_button.pack(side="left", padx=8)
        self.stop_button = ttk.Button(buttons, text="監視停止", command=self.stop, state="disabled")
        self.stop_button.pack(side="left")
        self.status = tk.StringVar(value="停止中")
        ttk.Label(buttons, textvariable=self.status).pack(side="left", padx=15)
        ttk.Label(frame, text="停止すると未送信予約を破棄します。送信済みのZapは取り消せません。", foreground="#8a4400").pack(anchor="w", pady=6)
        self.log = ScrolledText(frame, height=9, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)
        for control in self.controls:
            if isinstance(control, ttk.Entry):
                add_clipboard_menu(control)
        add_clipboard_menu(self.log)
        root.after(100, self.poll)

    def var(self, section, key, default):
        value = self.parser.get(section, key, fallback=default)
        if key == "output_mode":
            value = OUTPUT_LABELS.get(value.strip().lower(), value)
        if key == "auth_mode":
            value = AUTH_LABELS.get(value.strip().lower(), value)
        if key in ("enabled", "ignore_initial_history"):
            value = "true" if self.parser.getboolean(section, key, fallback=default == "true") else "false"
        variable = tk.StringVar(value=value)
        self.fields[section, key] = variable
        return variable

    def entry(self, parent, row, label, section, key, default, secret=False, width=65):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
        entry = ttk.Entry(parent, textvariable=self.var(section, key, default), width=width, show="*" if secret else "")
        entry.grid(row=row, column=1, sticky="w" if width < 20 else "ew", pady=3)
        self.controls.append(entry)

    def check(self, parent, label, section, key, default):
        control = ttk.Checkbutton(parent, text=label, variable=self.var(section, key, default), onvalue="true", offvalue="false")
        control.pack(side="left", padx=(0, 15))
        self.controls.append(control)

    def collect(self):
        parser = configparser.ConfigParser(interpolation=None)
        for (section, key), variable in self.fields.items():
            if not parser.has_section(section):
                parser.add_section(section)
            value = variable.get().strip()
            if key == "output_mode":
                value = OUTPUT_VALUES.get(value, value)
            if key == "auth_mode":
                value = AUTH_VALUES.get(value, value)
            if "\n" in value or "\r" in value:
                raise ValueError("設定値に改行を含めないでください。")
            parser.set(section, key, value)
        return parser

    def choose_oauth_client(self):
        path = filedialog.askopenfilename(parent=self.root, title="デスクトップアプリ用OAuthクライアントJSON",
                                          filetypes=[("JSON", "*.json")])
        if path:
            self.fields["YouTube", "oauth_client_file"].set(path)

    def forget_google_login(self):
        try:
            from youtube_auth import forget_login
            forget_login()
            self.status.set("保存済みGoogleログインを削除しました。次回開始時にログインします。")
        except Exception:
            messagebox.showerror("ログイン解除失敗", "保存済みログインを削除できませんでした。", parent=self.root)

    def save(self):
        try:
            save_config(self.collect(), self.path)
            self.status.set("設定を保存しました")
        except Exception as exc:
            messagebox.showerror("設定を保存できません", str(exc), parent=self.root)

    def start(self):
        if self.monitor.running:
            return
        try:
            video_id = extract_video_id(self.video.get())
            parser = self.collect()
            settings = settings_from_parser(parser)
            save_config(parser, self.path)
            self.secrets = [value for value in (settings.youtube_api_key, settings.pavlok_initial_token,
                           parser.get("Pavlok", "initial_token")) if value]
            self.monitor.start(video_id)
        except Exception as exc:
            messagebox.showerror("監視を開始できません", str(exc), parent=self.root)
            return
        self.stop_requested = False
        self.was_running = True
        self.set_running(True)
        self.status.set("接続中 / " + ("実送信ON" if settings.pavlok_enabled else "DRY-RUN"))

    def set_running(self, running):
        for control in self.controls:
            control.configure(state="disabled" if running else ("readonly" if isinstance(control, ttk.Combobox) else "normal"))
        self.start_button.configure(state="disabled" if running else "normal")
        self.save_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")

    def stop(self):
        self.stop_requested = True
        self.monitor.stop()
        self.status.set("停止処理中…")
        self.stop_button.configure(state="disabled")

    def poll(self):
        for _ in range(200):
            try:
                line = self.monitor.messages.get_nowait()
            except queue.Empty:
                break
            for secret in self.secrets:
                line = line.replace(secret, "[非表示]")
            if "[STREAM] 監視開始" in line and not self.stop_requested:
                self.status.set("監視中 / " + ("実送信ON" if self.fields['Pavlok', 'enabled'].get() == 'true' else 'DRY-RUN'))
            self.log.configure(state="normal")
            self.log.insert("end", line)
            if int(self.log.index("end-1c").split(".")[0]) > 2000:
                self.log.delete("1.0", "201.0")
            self.log.see("end")
            self.log.configure(state="disabled")
        reader_done = self.monitor.reader is None or not self.monitor.reader.is_alive()
        if self.was_running and not self.monitor.running and reader_done:
            self.was_running = False
            self.set_running(False)
            code = self.monitor.process.returncode
            self.status.set("停止しました（未送信予約は破棄）" if self.stop_requested else
                            ("監視終了" if code == 0 else "エラーで停止しました。ログを確認してください。"))
        if self.closing and not self.monitor.running and reader_done:
            self.root.destroy()
            return
        self.root.after(100, self.poll)

    def close(self):
        self.closing = True
        self.stop()


def run_gui():
    root = tk.Tk()
    try:
        SettingsWindow(root)
    except Exception as exc:
        messagebox.showerror("設定画面を開けません", str(exc), parent=root)
        root.destroy()
        return
    root.mainloop()
