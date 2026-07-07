"""簡單的問題頻率記錄（用於自動學習高頻問題）。"""
from __future__ import annotations

import json
from pathlib import Path

from text_encoding import read_text_bootstrap, write_text


def _freq_path() -> Path:
    return Path(__file__).resolve().parent / "keyword_data" / "frequency.json"


def record_question(question: str, min_len: int = 6) -> int:
    """記錄問題出現次數，返回當前頻率。"""
    q = (question or "").strip()
    if len(q) < min_len:
        return 0

    path = _freq_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {}
    if path.is_file():
        try:
            text, _ = read_text_bootstrap(path)
            data = json.loads(text) or {}
        except Exception:
            data = {}

    key = q.lower()
    data[key] = data.get(key, 0) + 1
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
    return data[key]


def get_frequency(question: str) -> int:
    path = _freq_path()
    if not path.is_file():
        return 0
    try:
        text, _ = read_text_bootstrap(path)
        data = json.loads(text) or {}
        return data.get(question.lower(), 0)
    except Exception:
        return 0
