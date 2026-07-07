from __future__ import annotations

import os
import re
from pathlib import Path

from app.schemas import Source
from app.services.text_utils import normalize_space, safe_read_text, tokenize


PROJECT_EXTENSIONS = {
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cc",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".md",
    ".txt",
    ".log",
    ".ini",
    ".cfg",
    ".conf",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".bat",
    ".ps1",
    ".cmake",
    ".mk",
    ".uvprojx",
    ".uvoptx",
}
SKIP_DIRS = {
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    "node_modules",
    ".next",
    ".venv",
    ".venv310",
    ".venv312",
    "build",
    "dist",
    "out",
    "bin",
    "obj",
    "Debug",
    "Release",
    ".web_mvp_storage",
}


class ProjectContext:
    def search(self, project_path: str, query: str, top_k: int = 8) -> list[Source]:
        root = self._resolve_root(project_path)
        if not root:
            return []
        terms = tokenize(query, 24)
        if not terms and query.strip():
            terms = [query.strip()]
        low_terms = [term.lower() for term in terms if term]
        hits: list[Source] = []
        if root.is_file():
            hits.extend(self._scan_file(root, root.parent, low_terms, top_k * 3))
        else:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
                for filename in filenames:
                    path = Path(dirpath) / filename
                    if path.suffix.lower() not in PROJECT_EXTENSIONS:
                        continue
                    try:
                        if path.stat().st_size > 2_000_000:
                            continue
                    except OSError:
                        continue
                    hits.extend(self._scan_file(path, root, low_terms, top_k * 3))
                    if len(hits) >= top_k * 6:
                        break
                if len(hits) >= top_k * 6:
                    break
        hits.sort(key=lambda item: item.score, reverse=True)
        return self._dedupe(hits, top_k)

    def _resolve_root(self, project_path: str) -> Path | None:
        raw = (project_path or "").strip().strip('"').strip("'")
        if not raw:
            return None
        try:
            root = Path(raw).expanduser().resolve()
        except OSError:
            return None
        if not root.exists():
            return None
        return root

    def _scan_file(self, path: Path, root: Path, low_terms: list[str], limit: int) -> list[Source]:
        try:
            text = safe_read_text(path)
        except Exception:
            return []
        rel = self._relative_title(path, root)
        title_low = rel.lower()
        title_score = sum(3.0 for term in low_terms if term in title_low)
        hits: list[Source] = []
        for line_no, raw_line in enumerate(text.splitlines(), 1):
            line = normalize_space(re.sub(r"<[^>]+>", " ", raw_line))
            if not line:
                continue
            line_low = line.lower()
            score = title_score + sum(1.0 for term in low_terms if term in line_low)
            if score <= 0:
                continue
            hits.append(
                Source(
                    path=str(path),
                    line=line_no,
                    title=f"工程/{rel}",
                    snippet=line[:420],
                    score=score,
                    retrieval="project_scan",
                    matched_issue=self._matched_issue(rel, line),
                )
            )
            if len(hits) >= limit:
                break
        return hits

    def _relative_title(self, path: Path, root: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.name

    def _matched_issue(self, title: str, snippet: str) -> str:
        low = f"{title}\n{snippet}".lower()
        if any(k in low for k in ("sleep", "wake", "pwr", "lightsleep", "deepsleep", "唤醒", "低功耗")):
            return "工程中的低功耗/唤醒实现或配置"
        if any(k in low for k in ("ota", "boot", "crc", "flash", "upgrade", "升级")):
            return "工程中的启动/升级/Flash 配置"
        if any(k in low for k in ("wifi", "wlan", "dhcp", "ssid")):
            return "工程中的 WiFi 初始化或配置"
        if any(k in low for k in ("ble", "gap", "gatt", "bond", "pair", "advert")):
            return "工程中的 BLE 流程或参数配置"
        if any(k in low for k in ("gpio", "uart", "adc", "timer", "i2c", "spi")):
            return "工程中的外设驱动或管脚配置"
        return "工程中疑似相关实现或配置"

    def _dedupe(self, hits: list[Source], top_k: int) -> list[Source]:
        out: list[Source] = []
        seen: set[str] = set()
        for hit in hits:
            key = f"{hit.path}:{hit.line}:{hit.snippet[:80]}"
            if key in seen:
                continue
            seen.add(key)
            out.append(hit)
            if len(out) >= top_k:
                break
        return out
