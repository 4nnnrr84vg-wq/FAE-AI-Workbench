from __future__ import annotations

import re
from pathlib import Path


ERROR_RE = re.compile(
    r"\b(?:[A-Z][A-Z0-9]+_){1,}[A-Z0-9_]+\b|"
    r"\b(?:0x[0-9a-fA-F]{4,})\b|"
    r"\b(?:ERR|ERROR|FAIL|FAILED|ASSERT|PANIC|FAULT)[A-Z0-9_:-]*\b",
    re.IGNORECASE,
)

VERSION_RE = re.compile(r"\b[vV]?\d+\.\d+(?:\.\d+)?(?:[-_][A-Za-z0-9.]+)?\b")
SDK_RE = re.compile(r"(?:SDK|sdk)\s*[:=： ]\s*([vV]?\d+\.\d+(?:\.\d+)?)")
FW_RE = re.compile(r"(?:firmware|fw|固件|版本)\s*[:=： ]\s*([vV]?\d+\.\d+(?:\.\d+)?)", re.I)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def unique_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        val = str(item).strip()
        key = val.lower()
        if not val or key in seen:
            continue
        seen.add(key)
        out.append(val)
    return out


def tokenize(text: str, limit: int = 16) -> list[str]:
    words = re.findall(
        r"0x[0-9a-fA-F]+|[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,8}|\d+\.\d+(?:\.\d+)?",
        text or "",
    )
    stop = {
        "客户",
        "问题",
        "怎么",
        "如何",
        "是否",
        "当前",
        "没有",
        "需要",
        "这个",
        "那个",
        "资料",
        "文档",
        "the",
        "and",
        "with",
        "from",
        "this",
        "that",
    }
    out: list[str] = []
    for word in words:
        if word.lower() in stop:
            continue
        out.append(word)
    return unique_keep_order(out)[:limit]


def extract_error_keywords(text: str, limit: int = 12) -> list[str]:
    return unique_keep_order([m.group(0) for m in ERROR_RE.finditer(text or "")])[:limit]


def safe_read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")
