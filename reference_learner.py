"""自动从 reference/documents/ 学习并生成关键词条目。"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from text_encoding import read_text_bootstrap, write_text

_REF_DIR = Path(__file__).resolve().parent / "reference" / "documents"
_STATE_FILE = Path(__file__).resolve().parent / "keyword_data" / "reference_learned.json"


@dataclass
class RefEntry:
    id: str
    keywords: list[str]
    reply: str
    priority: int = 70
    source: str = ""


def _file_hash(fp: Path) -> str:
    try:
        data = fp.read_bytes()
        return hashlib.md5(data).hexdigest()[:12]
    except Exception:
        return ""


def _load_state() -> dict:
    if not _STATE_FILE.is_file():
        return {}
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_entries_from_file(fp: Path) -> list[RefEntry]:
    """从单个文件里尝试抽取「问题-答案」对或标题-内容对。"""
    text, _ = read_text_bootstrap(fp)
    entries: list[RefEntry] = []
    rel = fp.relative_to(_REF_DIR).as_posix()

    # 简单规则 1：识别 "## 标题" 作为问题，下一段作为回答
    for m in re.finditer(r"^##\s+(.+?)$", text, re.M):
        title = m.group(1).strip()
        start = m.end()
        # 找下一个 ## 或文件结尾
        next_head = text.find("\n##", start)
        content = text[start : next_head if next_head != -1 else None].strip()[:400]
        if len(title) >= 4 and len(content) >= 10:
            eid = f"ref_{hashlib.md5((rel+title).encode()).hexdigest()[:10]}"
            entries.append(
                RefEntry(
                    id=eid,
                    keywords=[title],
                    reply=content,
                    priority=72,
                    source=rel,
                )
            )

    # 简单规则 2：文件名本身作为关键词（如果文件名有意义）
    stem = fp.stem
    if len(stem) >= 4 and not stem.startswith("新建"):
        # 取文件前 300 字作为回答
        summary = text[:300].replace("\n", " ").strip()
        eid = f"ref_{hashlib.md5(rel.encode()).hexdigest()[:10]}"
        entries.append(
            RefEntry(
                id=eid,
                keywords=[stem, rel],
                reply=summary,
                priority=65,
                source=rel,
            )
        )

    return entries


def learn_from_reference(force: bool = False) -> tuple[int, str]:
    """扫描 reference/documents/，生成关键词条目并写入 learned.yaml。"""
    if not _REF_DIR.is_dir():
        return 0, "reference/documents/ 不存在"

    state = _load_state()
    new_entries: list[dict] = []
    processed = 0

    for fp in _REF_DIR.rglob("*"):
        if not fp.is_file() or fp.suffix.lower() not in {".md", ".txt"}:
            continue
        h = _file_hash(fp)
        if not force and h and state.get(str(fp), "") == h:
            continue  # 文件没变，跳过

        entries = _extract_entries_from_file(fp)
        for e in entries:
            new_entries.append(
                {
                    "id": e.id,
                    "keywords": e.keywords,
                    "match": "contains",
                    "reply": e.reply,
                    "priority": e.priority,
                    "source": e.source,
                }
            )
        state[str(fp)] = h
        processed += 1

    if not new_entries:
        return 0, "没有新内容需要学习"

    # 写入 learned.yaml（追加模式）
    from keyword_learning import _ensure_learned_file, _load_learned_entries, _save_learned_entries

    learned_path = _ensure_learned_file()
    existing = _load_learned_entries(learned_path)
    # 去重：同 id 的保留新的
    id_set = {e.get("id") for e in existing}
    added = 0
    for e in new_entries:
        if e["id"] not in id_set:
            existing.append(e)
            id_set.add(e["id"])
            added += 1

    _save_learned_entries(learned_path, existing)
    _save_state(state)

    return added, f"已从 {processed} 个文件学习，新增 {added} 条关键词（来源 reference/documents/）"


def status_text() -> str:
    state = _load_state()
    return f"已记录 {len(state)} 个 reference 文件的哈希，防止重复学习。"