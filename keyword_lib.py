"""关键词库：命中即秒回，不走 Cursor AI。"""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from text_encoding import read_text_bootstrap


def _base_dir() -> Path:
    return Path(__file__).resolve().parent


def _is_garbled(text: str) -> bool:
    """判断是否为乱码。纯中文关键词不能因「高位字符比例高」被误杀。"""
    if not text:
        return False
    if any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in text):
        return True
    if "\ufffd" in text:
        return True

    # 正常简体中文：不算乱码
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    if cjk >= max(2, len(text) // 3):
        return False

    # 英文/数字/常见技术标识符
    if re.fullmatch(r"[\w\s\.\-_/`+:，、；]+", text, re.I):
        return False

    # 典型 UTF-8 误读 GB18030 的连续拉丁乱码
    if re.search(r"[\x80-\xFF]{4,}", text.encode("latin1", errors="ignore").decode("latin1", errors="ignore")):
        return True
    return False


def _normalize_query_text(s: str) -> str:
    """匹配前统一：去空白标点，联接/连接 视为同义。"""
    s = _normalize_exact_text(s)
    s = s.replace("联接", "连接")
    return s


def _normalize_entries(raw: list, *, default_priority: int = 0) -> list[dict]:
    entries: list[dict] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        reply = str(item.get("reply", "")).strip()
        if not reply:
            continue
        kws = item.get("keywords") or item.get("keyword") or []
        if isinstance(kws, str):
            kws = [kws]
        keywords = []
        for k in kws:
            k = str(k).strip()
            if not k:
                continue
            if _is_garbled(k):
                continue
            keywords.append(k)
        if not keywords:
            continue
        mode = str(item.get("match", "contains")).lower()
        if mode not in ("contains", "exact", "regex"):
            mode = "contains"
        priority = int(item.get("priority", default_priority))
        # 自动过滤低品质的 auto_ 学习条目（priority < 40 的直接丢弃，避免干扰）
        eid = str(item.get("id", ""))
        if eid.startswith("auto_") and priority < 40:
            continue
        entries.append(
            {
                "id": eid,
                "keywords": keywords,
                "match": mode,
                "reply": reply,
                "priority": priority,
            }
        )
    entries.sort(
        key=lambda e: (e["priority"], max(len(k) for k in e["keywords"])),
        reverse=True,
    )
    return entries


def _normalize_exact_text(s: str) -> str:
    """用于 exact 匹配的轻量规范化：去空白、去常见中英文标点、统一小写。"""
    if not s:
        return ""
    s = s.strip().lower()
    # 去掉所有空白
    s = re.sub(r"\s+", "", s)
    # 去掉常见中英文标点，避免“同问不同符号”无法命中
    s = re.sub(r"[，。！？、：；“”\"'`~!@#$%^&*()_\-+=\[\]{}<>?/\\|.]", "", s)
    return s


class KeywordLibrary:
    def __init__(self, config: dict):
        bot = config.get("bot", {})
        kl = config.get("keyword_learning", {})
        self.enabled = bool(bot.get("keyword_library_enabled", True))
        fname = str(bot.get("keyword_library_file", "keyword_library.yaml"))
        path = fname if os.path.isabs(fname) else str(_base_dir() / fname)
        self.path = path
        self.learned_path = self._resolve_learned_path(config)
        self.entries: list[dict] = []
        if self.enabled:
            self.reload(config)

    def _resolve_learned_path(self, config: dict) -> str:
        kl = config.get("keyword_learning", {})
        if not kl.get("enabled", True):
            return ""
        learned_name = str(kl.get("learned_file", "learned.yaml"))
        if os.path.isabs(learned_name):
            return learned_name
        data_dir = str(kl.get("data_dir", "keyword_data"))
        return str(_base_dir() / data_dir / Path(learned_name).name)

    def reload(self, config: dict | None = None) -> None:
        self.entries = []
        if not self.enabled:
            return
        merged: list[dict] = []
        merged.extend(self._load_file(self.path))
        if config:
            self.learned_path = self._resolve_learned_path(config)
        if self.learned_path:
            merged.extend(self._load_file(self.learned_path, default_priority=30))
        self.entries = _normalize_entries(merged)

    def _load_file(self, path: str, default_priority: int = 0) -> list[dict]:
        if not path or not os.path.isfile(path):
            return []
        try:
            text, _ = read_text_bootstrap(path)
            data = yaml.safe_load(text) or {}
            return _normalize_entries(data.get("entries", []), default_priority=default_priority)
        except Exception as e:
            print(f"[WARN] 关键词库加载失败 {path}: {e}")
            return []

    def match(self, text: str) -> tuple[str, str] | None:
        """返回 (reply, entry_id)；多关键词命中时取得分最高的一条。"""
        if not self.enabled or not self.entries:
            return None
        text = (text or "").strip()
        if not text:
            return None
        low = text.lower()
        norm_q = _normalize_query_text(text)

        best_entry: dict | None = None
        best_id = ""
        best_score = -1

        for entry in self.entries:
            mode = entry["match"]
            matched: list[str] = []
            for kw in entry["keywords"]:
                norm_kw = _normalize_query_text(kw)
                if mode == "exact" and norm_q == norm_kw:
                    matched.append(kw)
                elif mode == "contains" and (
                    kw in text
                    or kw.lower() in low
                    or (norm_kw and len(norm_kw) >= 4 and norm_kw in norm_q)
                ):
                    matched.append(kw)
                elif mode == "regex":
                    try:
                        if re.search(kw, text, re.I):
                            matched.append(kw)
                    except re.error:
                        continue
            if not matched:
                continue

            # exact 命中时优先返回（最高优先级）
            if mode == "exact":
                best_entry = entry
                best_id = entry["id"]
                best_score = 999999
                break

            max_kw_len = max(len(k) for k in matched)
            # 低优先级条目禁止仅凭「从机」等短泛词命中
            if entry["priority"] < 92 and max_kw_len < 4 and len(matched) < 2:
                continue
            score = (
                entry["priority"] * 1000
                + sum(len(k) for k in matched)
                + len(matched) * 20
            )
            if score > best_score:
                best_score = score
                best_entry = entry
                best_id = entry["id"] or matched[0]

        if best_entry:
            return {
                "reply": best_entry["reply"],
                "id": best_id,
                "score": best_score,
                "priority": int(best_entry["priority"]),
            }
        return None

    def count(self) -> int:
        return len(self.entries)
