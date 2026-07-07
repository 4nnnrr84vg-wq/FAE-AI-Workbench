"""项目统一文本编码。

当前工程文件以 UTF-8 为主；旧的 GB18030 文件仍可回退读取。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# 默认 UTF-8；环境变量 FILE_ENCODING 可覆盖
FILE_ENCODING = os.environ.get("FILE_ENCODING", "utf-8")

# 读取旧文件时的回退顺序（Python 源码不在此列，仍用 UTF-8）
_FALLBACK_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030")


def load_encoding_from_config(cfg: dict | None) -> str:
    global FILE_ENCODING
    if cfg:
        enc = str(cfg.get("bot", {}).get("file_encoding", "")).strip()
        if enc:
            FILE_ENCODING = enc
            os.environ["FILE_ENCODING"] = enc
    return FILE_ENCODING


def read_text_bootstrap(path: str | os.PathLike[str]) -> tuple[str, str]:
    """按多种编码尝试解码，返回 (文本, 检测到的编码)。"""
    raw = Path(path).read_bytes()
    if not raw:
        return "", FILE_ENCODING
    for enc in _FALLBACK_ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode(FILE_ENCODING, errors="replace"), FILE_ENCODING


def ensure_file_encoding(path: str | os.PathLike[str]) -> str:
    """若文件不是目标编码则重写为 FILE_ENCODING，返回最终文本。"""
    text, src_enc = read_text_bootstrap(path)
    if src_enc.lower().replace("_", "") != FILE_ENCODING.lower().replace("_", ""):
        write_text(path, text)
    return text


def load_yaml_config(path: str | os.PathLike[str]) -> dict:
    import yaml
    import re

    text = ensure_file_encoding(path)
    # 強制移除 YAML 不允許的控制字元（避免 #x0084 等非法字元導致解析失敗）
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    cfg = yaml.safe_load(text) or {}
    load_encoding_from_config(cfg)
    return cfg


def open_text(path: str | os.PathLike[str], mode: str = "r", **kwargs: Any):
    kwargs.setdefault("encoding", FILE_ENCODING)
    return open(path, mode, **kwargs)


def read_text(path: str | os.PathLike[str], *, errors: str = "strict") -> str:
    return Path(path).read_text(encoding=FILE_ENCODING, errors=errors)


def write_text(path: str | os.PathLike[str], text: str) -> None:
    Path(path).write_text(text, encoding=FILE_ENCODING)


def append_text(path: str | os.PathLike[str], text: str) -> None:
    with open_text(path, "a") as f:
        f.write(text)


def encode_str(text: str) -> bytes:
    return text.encode(FILE_ENCODING, errors="replace")
