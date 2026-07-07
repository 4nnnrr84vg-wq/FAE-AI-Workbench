"""根据问题文本解析并定位要发送的文件（数据手册、规格书等）。"""
from __future__ import annotations

import os
import re
from pathlib import Path

from text_encoding import load_yaml_config, write_text

_BASE = Path(__file__).resolve().parent
_CATALOG = _BASE / "file_data" / "catalog.yaml"

# 用户在问「要文件/手册/资料」
_FILE_REQUEST_RE = re.compile(
    r"(数据手册|规格书|datasheet|用户手册|技术手册|手册|文档|资料|说明书|原理图|"
    r"gerber|bom|sdk包|固件|驱动|驱动包|\.pdf|\.zip|\.xlsx|\.docx?)",
    re.I,
)
_FILE_INTENT_RE = re.compile(
    r"(提供|发一?下|给一?下|能否|可以|有没有|需要|要一?份|要一?个|发我|给我|分享|上传)",
    re.I,
)
_CHIP_RE = re.compile(r"\b(XC[A-Z]?\d{3,5}[A-Z0-9]*|[A-Z]{2,}\d{3,}[A-Z0-9]*)\b", re.I)
_TOKEN_RE = re.compile(r"[A-Za-z0-9]{3,}")

_EXT_PRIORITY = {
    ".pdf": 10,
    ".docx": 8,
    ".doc": 7,
    ".xlsx": 6,
    ".zip": 5,
    ".md": 2,
    ".txt": 1,
}


def is_file_request(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if t.startswith("/file"):
        return True
    return bool(_FILE_REQUEST_RE.search(t) and _FILE_INTENT_RE.search(t))


def extract_tokens(text: str) -> list[str]:
    """从问题里提取芯片型号、文件名片段等检索词。"""
    t = (text or "").strip()
    found: list[str] = []
    seen: set[str] = set()

    def add(tok: str) -> None:
        key = tok.lower()
        if len(tok) < 3 or key in seen:
            return
        seen.add(key)
        found.append(tok)

    for m in _CHIP_RE.finditer(t):
        add(m.group(1))
    for m in _TOKEN_RE.finditer(t):
        tok = m.group(0)
        if tok.lower() in {"pdf", "doc", "docx", "xlsx", "zip", "sdk", "ble"}:
            continue
        add(tok)
    return found


class FileResolver:
    def __init__(self, config: dict):
        self.config = config
        files_cfg = config.get("files", {}) or {}
        self.command_prefix = str(files_cfg.get("command_prefix", "/file"))
        self.mapping: dict[str, str] = dict(files_cfg.get("mapping", {}) or {})
        self.scan_dirs = self._resolve_scan_dirs(files_cfg.get("scan_dirs"))
        self.catalog = self._load_catalog()
        self._merge_catalog_into_mapping()

    def reload(self, config: dict) -> None:
        self.__init__(config)

    def _resolve_scan_dirs(self, raw) -> list[Path]:
        dirs: list[Path] = []
        if isinstance(raw, list) and raw:
            items = raw
        else:
            items = ["file_library", "reference/documents"]
        for item in items:
            p = Path(item)
            if not p.is_absolute():
                p = _BASE / p
            if p.is_dir():
                dirs.append(p)
        return dirs

    def _load_catalog(self) -> list[dict]:
        if not _CATALOG.is_file():
            return []
        try:
            data = load_yaml_config(str(_CATALOG))
            entries = data.get("entries", [])
            return entries if isinstance(entries, list) else []
        except Exception:
            return []

    def _merge_catalog_into_mapping(self) -> None:
        for entry in self.catalog:
            path = str(entry.get("path", "")).strip()
            if not path or not os.path.isfile(path):
                continue
            keys = entry.get("keywords") or [entry.get("key", "")]
            for k in keys:
                k = str(k).strip()
                if k:
                    self.mapping.setdefault(k, path)

    def try_resolve(self, text: str) -> dict | None:
        text = (text or "").strip()
        if not text:
            return None

        if text.startswith(self.command_prefix):
            key = text[len(self.command_prefix) :].strip()
            if key.lower().startswith("map "):
                return None
            if key:
                hit = self._hit_from_key(key)
                if hit:
                    return hit
            return None

        if not is_file_request(text):
            # 仍允许 config mapping 关键词直接出现在句子里（旧逻辑）
            for key in sorted(self.mapping.keys(), key=len, reverse=True):
                if key and key.lower() in text.lower():
                    hit = self._hit_from_key(key)
                    if hit:
                        return hit
            return None

        tokens = extract_tokens(text)
        if not tokens:
            return None

        for key in sorted(self.mapping.keys(), key=len, reverse=True):
            kl = key.lower()
            if kl in text.lower() or any(kl in tok.lower() or tok.lower() in kl for tok in tokens):
                hit = self._hit_from_key(key)
                if hit:
                    return hit

        scanned = self._scan_dirs(tokens, text)
        if scanned:
            self._remember(tokens, scanned)
            return scanned
        return None

    def resolve_or_message(self, text: str) -> dict:
        """返回 file action 或 text（未找到时的提示）。"""
        if text.startswith(self.command_prefix):
            arg = text[len(self.command_prefix) :].strip()
            if arg.lower().startswith("map "):
                return {"type": "text", "content": self._cmd_map(arg[4:].strip()), "reason": "file_cmd"}
            if arg.lower() in ("list", "列表", "status", "状态"):
                return {"type": "text", "content": self.status_text(), "reason": "file_cmd"}
            hit = self._hit_from_key(arg) if arg else None
            if hit:
                return {"type": "file", **hit}
            return {
                "type": "text",
                "content": f"未找到文件「{arg}」。可用 /file list 查看，或用 /file map 关键词 路径 注册。",
                "reason": "file_cmd",
            }

        hit = self.try_resolve(text)
        if hit:
            return {"type": "file", **hit}

        if is_file_request(text):
            toks = ", ".join(extract_tokens(text)[:4]) or "（未识别型号）"
            return {
                "type": "text",
                "content": (
                    f"未找到与「{toks}」匹配的文件。\n"
                    f"请将 PDF 放入 tools/wechat_bot/file_library/（文件名含型号），\n"
                    f"或在控制台输入：/file map XC6517 E:/path/to/XC6517.pdf"
                ),
                "reason": "file_not_found",
            }
        return {"type": "nlp_or_default"}

    def _hit_from_key(self, key: str) -> dict | None:
        path = self.mapping.get(key)
        if not path:
            for k, p in self.mapping.items():
                if k.lower() == key.lower():
                    path = p
                    key = k
                    break
        if not path:
            return None
        path = os.path.normpath(path)
        if not os.path.isfile(path):
            return None
        name = os.path.basename(path)
        return {
            "key": key,
            "path": path,
            "notice": f"已找到 {key} 相关文件：{name}（已复制到剪贴板，在微信 Ctrl+V 发送）",
        }

    def _scan_dirs(self, tokens: list[str], query: str) -> dict | None:
        if not self.scan_dirs:
            return None
        want_manual = bool(re.search(r"手册|datasheet|规格", query, re.I))
        best: tuple[int, Path] | None = None

        for root in self.scan_dirs:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in _EXT_PRIORITY:
                    continue
                score = self._score_path(path, tokens, want_manual)
                if score <= 0:
                    continue
                if best is None or score > best[0]:
                    best = (score, path)

        if not best:
            return None
        path = str(best[1].resolve())
        key = tokens[0] if tokens else best[1].stem
        name = best[1].name
        return {
            "key": key,
            "path": path,
            "notice": f"已找到 {key} 相关文件：{name}（已复制到剪贴板，在微信 Ctrl+V 发送）",
        }

    def _score_path(self, path: Path, tokens: list[str], want_manual: bool) -> int:
        name = path.name.lower()
        score = _EXT_PRIORITY.get(path.suffix.lower(), 0)
        matched = 0
        for tok in tokens:
            tl = tok.lower()
            if tl in name:
                matched += 1
                score += 20 if name.startswith(tl) else 12
        if matched == 0:
            return 0
        if matched == len(tokens):
            score += 8
        if want_manual and any(k in name for k in ("手册", "datasheet", "spec", "manual")):
            score += 6
        return score

    def _remember(self, tokens: list[str], hit: dict) -> None:
        files_cfg = self.config.get("files", {}) or {}
        if not bool(files_cfg.get("auto_catalog", True)):
            return
        path = hit.get("path", "")
        if not path or not os.path.isfile(path):
            return
        keywords = list(dict.fromkeys(tokens + [hit.get("key", "")]))
        keywords = [k for k in keywords if k]
        for entry in self.catalog:
            if os.path.normpath(str(entry.get("path", ""))) == os.path.normpath(path):
                old = [str(x) for x in entry.get("keywords", [])]
                merged = list(dict.fromkeys(old + keywords))
                entry["keywords"] = merged
                self._save_catalog()
                for k in merged:
                    self.mapping[k] = path
                return
        self.catalog.append({"keywords": keywords, "path": path})
        self._save_catalog()
        for k in keywords:
            self.mapping[k] = path

    def _save_catalog(self) -> None:
        _CATALOG.parent.mkdir(parents=True, exist_ok=True)
        lines = ["entries:"]
        for entry in self.catalog:
            kws = entry.get("keywords") or []
            path = entry.get("path", "")
            lines.append("  - keywords:")
            for k in kws:
                lines.append(f'      - "{k}"')
            lines.append(f'    path: "{path}"')
        write_text(_CATALOG, "\n".join(lines) + "\n")

    def _cmd_map(self, arg: str) -> str:
        parts = arg.strip().split(maxsplit=1)
        if len(parts) < 2:
            return "用法：/file map 关键词 文件完整路径\n示例：/file map XC6517 E:/docs/XC6517_datasheet.pdf"
        key, path = parts[0].strip(), parts[1].strip().strip('"')
        path = os.path.normpath(path)
        if not os.path.isfile(path):
            return f"文件不存在：{path}"
        self.mapping[key] = path
        self._remember([key], {"key": key, "path": path})
        return f"已注册：{key} -> {path}"

    def status_text(self) -> str:
        lines = ["已注册的文件映射："]
        seen_paths: set[str] = set()
        for key, path in sorted(self.mapping.items(), key=lambda x: x[0].lower()):
            np = os.path.normpath(path)
            if np in seen_paths:
                continue
            seen_paths.add(np)
            ok = "OK" if os.path.isfile(path) else "缺失"
            lines.append(f"  • {key} -> {path} [{ok}]")
        if len(lines) == 1:
            lines.append("  （暂无，请用 /file map 注册，或把 PDF 放入 file_library/）")
        scan = ", ".join(str(d) for d in self.scan_dirs) or "（无）"
        lines.append(f"自动扫描目录：{scan}")
        return "\n".join(lines)
