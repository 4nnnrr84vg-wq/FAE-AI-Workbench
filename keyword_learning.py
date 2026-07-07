"""关键词库自动学习：从 AI 答复、草稿、聊天记录中提取问答并写入 learned.yaml。"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
from pathlib import Path

import yaml

from text_encoding import read_text, read_text_bootstrap, write_text

_STOP_WORDS = frozenset(
    {
        "你好",
        "在吗",
        "谢谢",
        "帮忙",
        "请问",
        "怎么",
        "什么",
        "一下",
        "可以吗",
        "收到",
        "好的",
        "嗯",
        "哦",
    }
)


def _base_dir() -> Path:
    return Path(__file__).resolve().parent


def _slug_id(text: str) -> str:
    return "auto_" + hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()[:10]


def extract_keywords(question: str, max_count: int = 6) -> list[str]:
    q = (question or "").strip()
    if not q:
        return []
    found: list[str] = []
    if 4 <= len(q) <= 48:
        found.append(q)
    for w in re.findall(r"[\u4e00-\u9fff]{2,10}", q):
        if w not in _STOP_WORDS:
            found.append(w)
    for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_./-]{2,}", q):
        found.append(w)
    out: list[str] = []
    seen: set[str] = set()
    for w in found:
        key = w.lower()
        if key in seen or len(w) < 2:
            continue
        # 過濾明顯亂碼（非 printable 中文/英文/數字/常見符號）
        if any(ord(c) > 0xFFFF or (0xD800 <= ord(c) <= 0xDFFF) for c in w):
            continue
        if re.search(r"[\x00-\x1F\x7F-\x9F]", w):
            continue
        # 額外：如果單個詞包含大量高位元組，跳過
        high = sum(1 for c in w if ord(c) > 127)
        if high >= 3 and high / len(w) > 0.5:
            continue
        seen.add(key)
        out.append(w)
        if len(out) >= max_count:
            break
    return out


class KeywordLearner:
    def __init__(self, cfg: dict, base_dir: str | None = None):
        kl = cfg.get("keyword_learning", {})
        self.enabled = bool(kl.get("enabled", True))
        self.auto_learn = bool(kl.get("auto_learn", True))
        self.learn_from_drafts = bool(kl.get("learn_from_drafts", True))
        self.learn_from_imports = bool(kl.get("learn_from_imports", True))
        self.max_entries = int(kl.get("max_entries", 200))
        self.min_question_len = int(kl.get("min_question_len", 4))
        self.max_reply_len = int(kl.get("max_reply_len", 1200))
        self.min_reply_len = int(kl.get("min_reply_len", 16))
        self.learned_priority = int(kl.get("learned_priority", 65))
        self.command_prefix = str(kl.get("command_prefix", "/keyword"))
        root = Path(base_dir or _base_dir())
        data_dir = str(kl.get("data_dir", "keyword_data"))
        self.data_dir = root / data_dir
        self.imports_dir = self.data_dir / "imports"
        learned_name = str(kl.get("learned_file", "learned.yaml"))
        self.learned_path = (
            Path(learned_name) if os.path.isabs(learned_name) else self.data_dir / learned_name
        )
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.imports_dir.mkdir(parents=True, exist_ok=True)
        self._entries: list[dict] = []
        if self.enabled:
            self._load()

    def learned_file_path(self) -> str:
        return str(self.learned_path)

    def entries(self) -> list[dict]:
        return list(self._entries)

    def count(self) -> int:
        return len(self._entries)

    def _load(self) -> None:
        if not self.learned_path.is_file():
            self._entries = []
            return
        try:
            text, _ = read_text_bootstrap(self.learned_path)
            data = yaml.safe_load(text) or {}
            self._entries = list(data.get("entries", []) or [])
        except Exception:
            self._entries = []

    def _save(self) -> None:
        self.learned_path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "entries": self._entries,
            "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        write_text(
            self.learned_path,
            yaml.safe_dump(body, allow_unicode=True, sort_keys=False, default_flow_style=False),
        )

    def _is_duplicate(self, question: str, reply: str) -> bool:
        qn = question.strip().lower()
        for e in self._entries:
            if str(e.get("reply", "")).strip() == reply.strip():
                return True
            for kw in e.get("keywords") or []:
                if str(kw).strip().lower() == qn:
                    return True
        return False

    def _should_learn(self, question: str, reply: str, source: str) -> bool:
        if not self.enabled:
            return False
        q = question.strip()
        r = reply.strip()
        if len(q) < self.min_question_len or len(r) < self.min_reply_len:
            return False
        if len(r) > self.max_reply_len:
            return False
        # 回复过短且不像完整技术答复时不自动学习（避免只学到最后一句话）
        if source.startswith("auto_") and len(r) < 80 and "\n" not in r:
            if any(k in q for k in ("怎么", "如何", "配置", "移植", "从机", "ble")):
                return False
        if "[AI 失败]" in r:
            return False
        if r.startswith("收到，我稍后"):
            return False
        if self._is_duplicate(q, r):
            return False
        # 勿把「仅工程路径」式短回复学进去，会覆盖正确关键词库
        if "peripheral.uvprojx" in r and len(r) < 200:
            if any(k in q for k in ("浅睡", "唤醒", "按键", "sleep", "gpio", "配置")):
                return False
        if source == "local_search" and "暂不可用" in r[:80]:
            return False
        return True

    def learn_pair(self, question: str, reply: str, source: str = "auto") -> bool:
        """写入一条学习记录，成功返回 True。"""
        if not self._should_learn(question, reply, source):
            return False
        keywords = extract_keywords(question)
        if not keywords:
            return False

        entry_id = _slug_id(question)
        reply_trim = reply.strip()
        if len(reply_trim) > self.max_reply_len:
            reply_trim = reply_trim[: self.max_reply_len] + "\n…（已截断）"

        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_entry = {
            "id": entry_id,
            "source": source,
            "priority": self.learned_priority,
            "keywords": keywords,
            "match": "contains",
            "reply": reply_trim,
            "question": question.strip()[:200],
            "created": now,
            "hits": 0,
        }

        replaced = False
        for i, e in enumerate(self._entries):
            if e.get("id") == entry_id:
                new_entry["hits"] = int(e.get("hits", 0))
                new_entry["created"] = e.get("created", now)
                self._entries[i] = new_entry
                replaced = True
                break
        if not replaced:
            self._entries.append(new_entry)

        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries :]

        self._save()
        return True

    def try_auto_learn(self, question: str, reply: str, source: str) -> bool:
        if not self.auto_learn:
            return False
        # 允许 reference 自动学习（reference 成功回答后自动学成关键词）
        if source not in ("nlp", "local_search", "reference"):
            return False
        ok = self.learn_pair(question, reply, source=f"auto_{source}")
        if ok:
            print(f"[INFO] 关键词库已自动学习: {question[:40]}...", flush=True)
        return ok

    def learn_exact_reference_cache(self, question: str, reply: str) -> bool:
        """
        专门为 Reference 成功回答创建「精确问题缓存」。
        如果是重复/相关问题，只追加关键词，不新建条目。
        拒绝学习带 [[REFERENCE_CONTEXT]] 或指令的污染答案。
        """
        if not self.enabled or not self.auto_learn:
            return False

        q = question.strip()
        r = reply.strip()
        if len(q) < 4 or len(r) < 5:
            return False
        if len(r) > 2000:
            r = r[:2000] + "\n…（已截断）"

        # 污染过滤：拒绝学习带 REFERENCE_CONTEXT 或指令的答案
        if "[[REFERENCE_CONTEXT]]" in r or "只用一段话" in r or "像同事在微信里快速回答" in r:
            print("[WARN] 拒绝学习污染答案（含 REFERENCE_CONTEXT 或指令）", flush=True)
            return False

        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        r_key = r[:80].lower().strip()

        kw_list = [q]
        if "联接" in q or "连接" in q:
            alt = q.replace("联接", "连接") if "联接" in q else q.replace("连接", "联接")
            if alt != q:
                kw_list.append(alt)
        for extra in ("蓝牙联接成功", "蓝牙连接成功", "连接成功标志", "slave_connected", "GAPC_CONNECTION_REQ_IND"):
            if extra in q or any(t in q for t in ("标志", "联接", "连接", "蓝牙")):
                if extra not in kw_list:
                    kw_list.append(extra)

        # 先查找是否已有相同答案的条目（避免重复创建）
        for i, e in enumerate(self._entries):
            src = str(e.get("source", ""))
            if not src.startswith("reference_exact_cache"):
                continue
            existing_reply = (e.get("reply") or "")[:80].lower().strip()
            if existing_reply != r_key:
                continue
            # 合并到同一条，并删除多余的 _contains 重复项
            kws = list(e.get("keywords") or [])
            for kw in kw_list[:10]:
                if kw not in kws:
                    kws.append(kw)
            e["keywords"] = kws[:12]
            e["match"] = "contains"
            e["question"] = q[:200]
            e["created"] = now
            # 删掉同答案的 _contains 兄弟条目
            base_id = str(e.get("id", "")).replace("_contains", "")
            self._entries = [
                x for x in self._entries
                if not (
                    str(x.get("id", "")) == base_id + "_contains"
                    or (
                        str(x.get("source", "")) == "reference_exact_cache_contains"
                        and (x.get("reply") or "")[:80].lower().strip() == r_key
                    )
                )
            ]
            self._save()
            print(f"[INFO] Reference 缓存已合并关键词（单条）: {q[:30]}...", flush=True)
            return True

        # 没有找到相同答案，才新建
        entry_id = "ref_cache_" + _slug_id(q)
        # 只建一条：contains + 细分关键词
        new_entry = {
            "id": entry_id,
            "source": "reference_exact_cache",
            "priority": 95,
            "keywords": kw_list[:10],
            "match": "contains",
            "reply": r,
            "question": q[:200],
            "created": now,
            "hits": 0,
        }
        self._entries.append(new_entry)

        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries:]

        self._save()
        print(f"[INFO] 已缓存 Reference 精确问题（下次秒回）: {q[:40]}...", flush=True)
        return True

    def learn_reference_fuzzy_cache(self, question: str, reply: str) -> bool:
        """
        为 Reference 成功回答创建「模糊关键词快取」（contains + 高优先级 90）。
        如果是重复/相关问题，只追加关键词，不新建条目。
        拒绝学习带 [[REFERENCE_CONTEXT]] 或指令的污染答案。
        """
        if not self.enabled or not self.auto_learn:
            return False

        q = question.strip()
        r = reply.strip()
        if len(q) < 6 or len(r) < 5:
            return False
        if len(r) > 2000:
            r = r[:2000] + "\n…（已截断）"

        # 污染过滤：拒绝学习带 REFERENCE_CONTEXT 或指令的答案
        if "[[REFERENCE_CONTEXT]]" in r or "只用一段话" in r or "像同事在微信里快速回答" in r:
            print("[WARN] 拒绝学习污染答案（含 REFERENCE_CONTEXT 或指令）", flush=True)
            return False

        keywords = extract_keywords(q, max_count=6)
        keywords = [k for k in keywords if len(k) >= 3 and k not in _STOP_WORDS]
        if not keywords:
            return False

        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        r_key = r[:80].lower().strip()

        # 先查找是否已有相同答案的条目
        for i, e in enumerate(self._entries):
            if e.get("source", "").startswith("reference_fuzzy_cache"):
                existing_reply = (e.get("reply") or "")[:80].lower().strip()
                if existing_reply == r_key:
                    # 追加新关键词（去重）
                    kws = e.get("keywords", [])
                    for kw in keywords:
                        if kw not in kws:
                            kws.append(kw)
                    e["keywords"] = kws[:8]  # 最多保留 8 个
                    e["question"] = q[:200]
                    e["created"] = now
                    self._save()
                    print(f"[INFO] Reference 模糊缓存已追加关键词: {keywords[0] if keywords else q[:20]}", flush=True)
                    return True

        # 没有找到相同答案，才新建
        entry_id = "ref_fuzzy_" + _slug_id(q)
        new_entry = {
            "id": entry_id,
            "source": "reference_fuzzy_cache",
            "priority": 90,
            "keywords": keywords[:6],
            "match": "contains",
            "reply": r,
            "question": q[:200],
            "created": now,
            "hits": 0,
        }
        self._entries.append(new_entry)

        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries:]

        self._save()
        print(f"[INFO] 已缓存 Reference 模糊关键词（意思相近可秒回）: {q[:40]}...", flush=True)
        return True

    def learn_from_drafts(self, draft_path: str) -> tuple[int, str]:
        if not os.path.isfile(draft_path):
            return 0, f"草稿文件不存在: {draft_path}"
        text = read_text(draft_path, errors="ignore")
        blocks = text.split("-" * 60)
        added = 0
        for block in blocks:
            incoming = ""
            draft = ""
            reason = ""
            for line in block.splitlines():
                if line.startswith("incoming="):
                    incoming = line[len("incoming=") :].strip()
                elif line.startswith("draft=TEXT:"):
                    draft = line[len("draft=TEXT:") :].strip()
                elif line.startswith("reason="):
                    reason = line[len("reason=") :].strip()
            if not incoming or not draft:
                continue
            if reason in ("nlp", "local_search") or reason.startswith("auto_"):
                if self.learn_pair(incoming, draft, source="draft"):
                    added += 1
        return added, f"从草稿学习 {added} 条 → {self.learned_path}"

    def learn_from_imports(self, cfg: dict) -> tuple[int, str]:
        from style_profile import StyleLearner

        sl = StyleLearner(cfg)
        if not sl.my_names:
            return 0, "导入学习需配置 style_learning.my_names（区分你与对方）"

        files = sorted(
            p
            for p in self.imports_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".txt", ".log", ".csv", ".json"}
        )
        if not files:
            files = sorted(
                p
                for p in sl.imports_dir.iterdir()
                if p.is_file() and p.suffix.lower() in {".txt", ".log", ".csv", ".json"}
            )
        if not files:
            return 0, f"请将聊天记录放到 {self.imports_dir} 或 style_data/imports/"

        added = 0
        for path in files:
            text = read_text(path, errors="ignore")
            pending_q = ""
            for speaker, content in sl._parse_lines(text):
                content = content.strip()
                if not content:
                    continue
                if sl._is_me(speaker):
                    if pending_q and self.learn_pair(pending_q, content, source="import"):
                        added += 1
                    pending_q = ""
                else:
                    if len(content) >= self.min_question_len:
                        pending_q = content
        return added, f"从聊天记录学习 {added} 条 → {self.learned_path}"

    def status_text(self) -> str:
        if not self.enabled:
            return "关键词学习未启用（keyword_learning.enabled=false）"
        return (
            f"已学习 {self.count()} 条（自动+导入）\n"
            f"文件：{self.learned_path}\n"
            f"自动学习：{'开' if self.auto_learn else '关'}\n"
            f"导入目录：{self.imports_dir}"
        )

    def record_hit(self, entry_id: str) -> None:
        if not entry_id or not entry_id.startswith("auto_"):
            return
        for e in self._entries:
            if e.get("id") == entry_id:
                e["hits"] = int(e.get("hits", 0)) + 1
                self._save()
                break

    def list_entries(self, limit: int = 20) -> list[dict]:
        return self._entries[-limit:][::-1]

    def delete_entry(self, entry_id: str) -> bool:
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.get("id") != entry_id]
        if len(self._entries) < before:
            self._save()
            return True
        return False

    def export_yaml(self) -> str:
        import yaml
        return yaml.safe_dump({"entries": self._entries}, allow_unicode=True, sort_keys=False)
