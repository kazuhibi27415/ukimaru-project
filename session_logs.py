"""GUI監視ログ。最大7日・10回、1回あたり末尾約2MBを保持する。"""
from datetime import datetime
import os
from pathlib import Path
import re
import time
import uuid

MAX_BYTES = 1024 * 1024


def log_dir():
    local = Path(os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData' / 'Local'))
    return local / 'PavlokSuperChat' / 'logs'


def redact(text, secrets=()):
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, '[非表示]')
    text = re.sub(r'(?i)(Bearer\s+)[^\s\"\'<>]+', r'\1[非表示]', text)
    text = re.sub(r'eyJ[\w-]+\.[\w-]+\.[\w-]+|AIza[\w-]{30,}|ya29\.[\w.-]+|1//[\w-]+', '[非表示]', text)
    text = re.sub(r'(?i)((?:api_key|key|initial_token|access_token|refresh_token|client_secret|token|code)\s*[\"\']?\s*[:=]\s*[\"\']?)[^\s\"\'&,}]+', r'\1[非表示]', text)
    return text


class SessionLog:
    def __init__(self, secrets=(), directory=None):
        self.secrets = tuple(secrets)
        self.directory = Path(directory) if directory is not None else log_dir()
        self.path = None
        self.failed = False
        self.last_cleanup = 0
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.path = self.directory / (datetime.now().strftime('session-%Y%m%d-%H%M%S%f-') + uuid.uuid4().hex + '.log')
            self.path.touch(exist_ok=False)
            self.cleanup()
            self.write('[SESSION] 監視開始 ' + datetime.now().isoformat(timespec='seconds') + '\n')
        except OSError:
            self.failed = True

    def cleanup(self):
        groups = {}
        for path in self.directory.iterdir():
            if not re.fullmatch(r'session-\d{8}-\d{6}(?:\d{6})?-[0-9a-f]{32}\.log(?:\.1)?', path.name):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            base = path.name.removesuffix('.1')
            groups.setdefault(base, []).append(path)
        ordered = sorted(groups, reverse=True)
        for index, base in enumerate(ordered):
            paths = groups[base]
            if self.path and base == self.path.name:
                continue
            if index >= 10 or max(p.stat().st_mtime for p in paths) < time.time() - 7 * 86400:
                for path in paths:
                    path.unlink(missing_ok=True)
        self.last_cleanup = time.time()

    def write(self, text):
        if self.failed:
            return
        try:
            data = redact(text, self.secrets).encode('utf-8', errors='replace')
            # 異常に長い一行でもファイル上限を大きく超えない。
            data = data[:MAX_BYTES].decode('utf-8', errors='ignore').encode('utf-8')
            if self.path.stat().st_size + len(data) > MAX_BYTES:
                os.replace(self.path, self.path.with_suffix('.log.1'))
            with self.path.open('ab') as handle:
                handle.write(data)
            if time.time() - self.last_cleanup > 3600:
                self.cleanup()
        except OSError:
            self.failed = True

    def close(self):
        self.write('[SESSION] 監視終了 ' + datetime.now().isoformat(timespec='seconds') + '\n')
