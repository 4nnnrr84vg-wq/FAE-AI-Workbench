"""模型接口不可用时的本仓库关键词检索（生成简要答复）。"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from text_encoding import read_text_bootstrap

# 仓库源码多为 UTF-8；聊天记录等本项目文件为 GB18030
CODE_FILE_ENCODING = "utf-8"

_REF_DIR = Path(__file__).resolve().parent / "reference" / "documents"
_REF_EXT = {".txt", ".md", ".yaml", ".yml", ".json", ".csv", ".log"}


def _clean_html(text: str) -> str:
    """去除 HTML 标签和实体，返回可读文本（用于 fallback 展示）。"""
    if not text:
        return ""
    # 去掉 HTML 标签
    t = re.sub(r"<[^>]+>", " ", text)
    # 常见实体
    t = t.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    t = t.replace("&#160;", " ").replace("&amp;", "&")
    # 压缩空白
    t = re.sub(r"\s+", " ", t).strip()
    return t[:200]  # 最多保留 200 字，避免太长

# reference 命中行相關度過濾關鍵詞（必須同時出現才算高品質）
_CONN_STRENGTH = {"连接", "connect", "link", "并发", "concurrent", "同时", "多", "最大", "个数", "数量", "max", "num", "count"}

# BLE 绑定/多连接相关强信号词（绑定 ≈ 连接管理）
_BONDING_HINTS = {"绑定", "bond", "bonding", "pairing", "配对", "app_sec", "security"}

# 中文问题 -> 检索词
_QUERY_TERMS: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"从机.*浅睡|ble.*peripheral.*浅睡|浅睡.*按键", re.I), ["gpio_lightsleep_wake", "Sleep_Demo", "sleep_init", "xc_pwr_gpio_lightsleep_wake"]),
    (re.compile(r"浅睡|light\s*sleep|lightsleep", re.I), ["lightsleep", "xc_pwr_gpio_lightsleep_wake", "system_lightsleep"]),
    (re.compile(r"io\s*唤醒|gpio.*唤醒|唤醒", re.I), ["wake_config", "xc_pwr_gpio", "wake_it", "GPIO_IRQn_WAKE"]),
    (re.compile(r"深睡|deepsleep|deep\s*sleep", re.I), ["deepsleep", "xc_pwr_pd_deepsleep"]),
    (re.compile(r"ota|升级", re.I), ["fast_ota", "ota_flash", "app_crc"]),
    (re.compile(r"ble|蓝牙", re.I), ["ble_", "gapc", "gatt"]),
    # 多连接 / 绑定相关（绑定 ≈ 连接管理，KXYJ-223 / CSALL-21 等 ticket）
    (re.compile(r"多连接|多连|multi.?connect|concurrent|同时连接|最大连接|连接数|多设备|绑定|bonding", re.I), ["multi_connection", "concurrent", "多连接", "绑定", "bond", "app_sec"]),
]

_SKIP_DIRS = {
    ".git", ".venv", ".venv312", "node_modules", "mdk", "output", "build",
    "__pycache__", ".cursor",
}
_EXT_OK = {".c", ".h", ".md", ".txt"}


def _terms_for_query(query: str) -> list[str]:
    terms: list[str] = []
    for pat, words in _QUERY_TERMS:
        if pat.search(query):
            terms.extend(words)
    # 拆中文（2字以上）+ 英文标识符
    for w in re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z_][a-zA-Z0-9_]{2,}", query):
        terms.append(w)
    # 原始完整问题（最重要，确保 reference 能被搜到）
    raw = query.strip()
    if raw and raw not in terms:
        terms.append(raw)
    # 额外加入常见 SDK 关键词，提高 reference 命中率
    extra = ["ble", "从机", "主机", "连接", "唤醒", "睡眠", "flash", "ota", "gpio", "pwr", "watchdog", "nvds", "multi"]
    for e in extra:
        if e not in terms:
            terms.append(e)
    return list(dict.fromkeys(terms))[:12]


def _rg_search(root: Path, term: str, limit: int) -> list[str]:
    try:
        proc = subprocess.run(
            ["rg", "-n", "--max-count", "3", "-i", term, str(root)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if proc.returncode in (0, 1) and proc.stdout:
            lines = []
            for line in proc.stdout.splitlines():
                if len(lines) >= limit:
                    break
                lines.append(line)
            return lines
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return []


def _walk_search(root: Path, term: str, limit: int) -> list[str]:
    hits: list[str] = []
    low = term.lower()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if Path(fn).suffix.lower() not in _EXT_OK:
                continue
            fp = Path(dirpath) / fn
            try:
                if fp.stat().st_size > 400_000:
                    continue
                text = fp.read_text(encoding=CODE_FILE_ENCODING, errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if low in line.lower():
                    rel = fp.relative_to(root).as_posix()
                    hits.append(f"{rel}:{i}:{line.strip()[:120]}")
                    if len(hits) >= limit:
                        return hits
    return hits


def _is_relevant_ref_hit(line: str, query: str, term: str) -> bool:
    """判断 reference 命中行是否真正与「多连接」等核心问题相关（更严格）。"""
    l = line.lower()
    q = query.lower()

    # 多连接 / 绑定类问题
    multi_intent = any(k in q for k in ("多连接", "multi", "concurrent", "同时连接", "连接数", "最大连接", "绑定"))
    if multi_intent:
        # 强信号：明确提到连接数、最大连接、concurrent、绑定、app_sec 等
        strong = any(k in l for k in ("连接数", "最大连接", "concurrent", "max_conn", "同时连接", "多连接", "绑定", "bond", "app_sec", "security"))
        if strong:
            return True
        # 允许「连接」+「多/最大/绑定」同时出现，且和从机/peripheral 相关
        if ("连接" in l or any(k in l for k in _BONDING_HINTS)) and any(k in l for k in ("多", "最大", "绑定", "bond")):
            if "从机" in l or "peripheral" in l or "ble" in l or "app_sec" in l:
                return True
        # 直接提到具体 Jira ticket（KXYJ-223, CSALL-21 等）也视为高品质
        if any(t in line for t in ("KXYJ-223", "CSALL-21", "KXYJ", "CSALL")):
            return True
        return False

    # 普通情况：只要命中行包含连接强度词就接受
    if any(k in l for k in _CONN_STRENGTH):
        return True
    return False


def _walk_reference(term: str, limit: int, query: str = "") -> list[str]:
    """检索 tools/wechat_bot/reference/documents/ 下的用户资料（带相关度过滤）。"""
    if not _REF_DIR.is_dir():
        return []
    hits: list[str] = []
    low = term.lower()
    for dirpath, _, filenames in os.walk(_REF_DIR):
        for fn in filenames:
            if Path(fn).suffix.lower() not in _REF_EXT:
                continue
            fp = Path(dirpath) / fn
            try:
                if fp.stat().st_size > 800_000:
                    continue
                text, _ = read_text_bootstrap(fp)
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if low in line.lower():
                    if query and not _is_relevant_ref_hit(line, query, term):
                        continue
                    rel = fp.relative_to(_REF_DIR).as_posix()
                    hits.append(f"[资料] {rel}:{i}:{line.strip()[:120]}")
                    if len(hits) >= limit:
                        return hits
    return hits


def _search_reference_broadly(query: str, limit: int) -> list[str]:
    """对任意问题都尝试在 reference/documents 里做广义检索。"""
    if not _REF_DIR.is_dir():
        return []
    # 用完整问题 + 拆出的词 一起搜
    candidates = [query.strip()]
    for w in re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z_][a-zA-Z0-9_]{2,}", query):
        if w not in candidates:
            candidates.append(w)
    all_hits: list[str] = []
    seen: set[str] = set()
    for term in candidates[:6]:  # 最多尝试前6个
        if not term or len(term) < 2:
            continue
        hits = _walk_reference(term, 3, query)
        for h in hits:
            if h not in seen:
                seen.add(h)
                all_hits.append(h)
                if len(all_hits) >= limit:
                    return all_hits
    return all_hits


def build_local_reply(query: str, workspace: str) -> str:
    root = Path(workspace)
    if not root.is_dir():
        return ""

    terms = _terms_for_query(query)

    all_hits: list[str] = []
    per_term = 4
    for term in terms:
        ref_chunk = _walk_reference(term, per_term, query)
        all_hits.extend(ref_chunk)
        chunk = _rg_search(root, term, per_term)
        if not chunk:
            chunk = _walk_search(root, term, per_term)
        all_hits.extend(chunk)

    # 廣義 reference 檢索（確保任意問題都能嘗試找 reference 資料）
    ref_only = [h for h in all_hits if h.startswith("[资料]")]
    if len(ref_only) == 0:
        broad = _search_reference_broadly(query, 8)
        all_hits.extend(broad)
        ref_only = [h for h in all_hits if h.startswith("[资料]")]

    # 如果有找到 reference 資料，優先回傳以 reference 為主的摘要
    # 多连接类问题若高品質資料太少（<2 条），则放弃 reference 答案，避免返回无关内容
    multi_intent = any(k in query.lower() for k in ("多连接", "multi", "concurrent", "同时连接", "连接数", "最大连接"))
    if ref_only:
        seen: set[str] = set()
        unique_ref: list[str] = []
        for h in all_hits:
            if h.startswith("[资料]") and h not in seen:
                seen.add(h)
                unique_ref.append(h)
            if len(unique_ref) >= 10:
                break

        if multi_intent and len(unique_ref) < 3:
            # 资料不足，跳过 reference 答案，让系统走 AI
            pass
        else:
            # 回传 reference context 格式，交由 AI 整合成自然回答
            body = "\n".join(f"  - {h}" for h in unique_ref)
            return (
                "[[REFERENCE_CONTEXT]]\n"
                f"问题：{query}\n"
                f"检索词：{', '.join(terms[:6])}\n\n"
                f"{body}"
            )

    # 去重保序
    seen: set[str] = set()
    unique: list[str] = []
    for h in all_hits:
        if h not in seen:
            seen.add(h)
            unique.append(h)
        if len(unique) >= 15:
            break

    # 多连接类问题若最终只剩下低品质 reference 结果，强制返回空，让系统走 AI
    if multi_intent:
        ref_hits = [h for h in unique if h.startswith("[资料]")]
        if len(ref_hits) > 0 and len(ref_hits) < 3:
            return ""

    # 清理 HTML 标签后再展示（fallback 模式下用户直接看到）
    cleaned = [_clean_html(h) for h in unique]
    body = "\n".join(f"  - {c}" for c in cleaned if c)
    return (
        "（模型接口暂不可用，以下为仓库内检索摘要，供参考）\n\n"
        f"检索词：{', '.join(terms)}\n\n"
        f"{body}\n\n"
        "也可查阅：`tools/wechat_bot/reference/documents/` 里你自建的资料。\n"
        "若需完整 AI 分析，请配置 model_api.enabled=true 并提供 base_url / api_key。"
    )
