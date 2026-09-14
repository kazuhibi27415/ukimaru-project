"""公開リリースだけを、起動時にバックグラウンドで確認する。"""
import re
import requests

RELEASES_URL = "https://github.com/kazuhibi27415/PavlokSuperChat-Project/releases/latest"
API_URL = "https://api.github.com/repos/kazuhibi27415/PavlokSuperChat-Project/releases/latest"


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"v?\d{1,5}\.\d{1,5}(?:\.\d{1,5})?", value):
        return None
    parts = tuple(map(int, value.lstrip('v').split('.')))
    return parts + (0,) * (3 - len(parts))


def newer_release(current):
    try:
        response = requests.get(API_URL, timeout=(3, 5), headers={"Accept": "application/vnd.github+json"})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
            return None
        tag = data.get('tag_name')
        latest, installed = version_tuple(tag), version_tuple(current)
        return tag if latest and installed and latest > installed else None
    except (requests.RequestException, ValueError):
        return None
