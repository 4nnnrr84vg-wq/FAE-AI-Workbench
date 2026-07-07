"""工程路径增强回答：结合微信问题、资料库和指定工程给出方案。"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from clipboard_payload import save_images_to_cache
from image_ocr import build_enriched_prompt, extract_text_from_paths
from local_search import build_local_reply


def _section(cfg: dict) -> dict:
    return cfg.get("project_assistant", {}) or {}


def enabled(cfg: dict) -> bool:
    return bool(_section(cfg).get("enabled", True))


def prompt_project_path(cfg: dict, state: dict) -> str:
    """提示输入工程路径。空字符串表示跳过工程增强，直接普通回答。"""
    if not enabled(cfg):
        return ""
    sec = _section(cfg)
    if not bool(sec.get("prompt_project_path", True)):
        return ""

    last = str(state.get("last_project_path", "") or "")
    hint = "回车=直接回答"
    if last:
        hint += f"，.=上次路径 {last}"
    print("\n[PROJECT] 工程路径？（可把文件夹拖到这里；" + hint + "）", flush=True)
    try:
        raw = input("[PROJECT] project> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[PROJECT] 已跳过工程增强回答", flush=True)
        return ""

    if not raw:
        return ""
    if raw == "." and last:
        raw = last

    path = _clean_path(raw)
    if not os.path.isdir(path):
        print(f"[WARN] 工程路径不存在，改为普通回答: {path}", flush=True)
        suggestions = _suggest_existing_dirs(path)
        if suggestions:
            print("[WARN] 你可能想输入:", flush=True)
            for item in suggestions:
                print(f"       {item}", flush=True)
        return ""

    resolved = str(Path(path).resolve())
    state["last_project_path"] = resolved
    return resolved


def generate_project_reply(
    bot,
    *,
    question: str,
    raw_text: str = "",
    images: list[bytes] | None = None,
    project_path: str,
    force_ai: bool = False,
) -> str:
    """只使用 model_api，结合资料库和工程检索生成回答/方案。"""
    cfg = bot.cfg
    sec = _section(cfg)
    images = images or []
    max_images = int(sec.get("max_images", 4))

    image_paths: list[str] = []
    ocr_text = ""
    if images:
        image_paths = save_images_to_cache(
            images,
            project_path,
            subdir=str(sec.get("image_subdir", ".wechat_bot_project/images")),
            max_images=max_images,
        )
        try:
            ocr_text = extract_text_from_paths(image_paths)
        except Exception as e:
            print(f"[WARN] 图片 OCR 失败: {e}", flush=True)

    user_text = build_enriched_prompt(raw_text or question, ocr_text)
    if not user_text.strip():
        user_text = question

    print(f"[PROJECT] 工程增强回答: {project_path}", flush=True)
    if image_paths:
        print(f"[PROJECT] 图片已保存 {len(image_paths)} 张", flush=True)
    if ocr_text:
        print(f"[PROJECT] OCR: {ocr_text.replace(chr(10), ' ')[:80]}...", flush=True)

    reference_context = ""
    if bool(sec.get("include_reference_context", True)):
        reference_context = build_local_reply(user_text, project_path)

    project_hits = ""
    if bool(sec.get("include_project_hits", True)):
        project_hits = _project_search(user_text, project_path, int(sec.get("max_project_hits", 12)))

    context = _build_context(
        project_path=project_path,
        question=question,
        raw_text=raw_text,
        image_paths=image_paths,
        ocr_text=ocr_text,
        reference_context=reference_context,
        project_hits=project_hits,
    )
    prompt = _build_prompt(user_text, force_ai=force_ai)

    reply = bot.model.generate_reply(prompt, context_text=context, prefer_model_api=True)
    if reply:
        return reply

    err = getattr(bot.model, "last_error", "") or "model_api 未返回内容"
    print(f"[WARN] 工程增强 AI 失败: {err}", flush=True)
    fallback = [
        "模型接口暂时连不上，我先按本地资料库和工程检索给一个初步判断：",
        _compact_local_context(reference_context, project_hits),
        "",
        "建议先确认网络/代理恢复后再按 Ctrl+R 重新生成；如果急着回复客户，可以先基于上面的本地线索说明。"
    ]
    return "\n".join(part for part in fallback if part).strip()[:1800]


def _build_prompt(user_text: str, *, force_ai: bool = False) -> str:
    mode = "请跳过缓存，重新完整分析。" if force_ai else ""
    return (
        f"{mode}\n"
        "请结合客户问题、资料库/数据手册线索和指定工程代码，给出可以直接回复客户的简洁答案。"
        "如果问题需要工程改动，请不要实际修改代码，只给出修改方案、影响范围、风险和验证方法。"
        "如果信息不足，请先明确列出还需要客户或工程侧补充什么。"
        "回答优先一段话，必要时用少量条目。\n\n"
        f"客户问题：{user_text}"
    )


def _build_context(
    *,
    project_path: str,
    question: str,
    raw_text: str,
    image_paths: list[str],
    ocr_text: str,
    reference_context: str,
    project_hits: str,
) -> str:
    images = "\n".join(f"- {p}" for p in image_paths) if image_paths else "无"
    return f"""[工程路径]
{project_path}

[客户问题]
{question}

[原始文本]
{raw_text or "无，仅图片/剪贴板内容"}

[图片路径]
{images}

[图片 OCR]
{ocr_text or "无"}

[资料库/数据手册/本地知识库线索]
{reference_context or "未命中"}

[工程代码命中线索]
{project_hits or "未命中"}
"""


def _project_search(query: str, project_path: str, limit: int) -> str:
    root = Path(project_path)
    if not root.is_dir():
        return ""
    terms = _terms(query)
    if not terms:
        return ""
    hits: list[str] = []
    seen: set[str] = set()
    for term in terms:
        for line in _rg(root, term, max(2, limit // max(1, len(terms[:5])))):
            if line in seen:
                continue
            seen.add(line)
            hits.append(line)
            if len(hits) >= limit:
                return "\n".join(f"- {h}" for h in hits)
    return "\n".join(f"- {h}" for h in hits)


def _compact_local_context(reference_context: str, project_hits: str) -> str:
    lines: list[str] = []
    for source in (reference_context, project_hits):
        for raw in (source or "").splitlines():
            line = raw.strip().lstrip("-").strip()
            if not line:
                continue
            if line.startswith("[[REFERENCE_CONTEXT]]") or line.startswith("问题：") or line.startswith("检索词："):
                continue
            line = re.sub(r"<[^>]+>", " ", line)
            line = line.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
            line = re.sub(r"\s+", " ", line).strip()
            if len(line) > 180:
                line = line[:180] + "..."
            if line and line not in lines:
                lines.append(line)
            if len(lines) >= 8:
                break
        if len(lines) >= 8:
            break
    if not lines:
        return "本地资料库和工程里没有检索到明确线索。"
    return "\n".join(f"- {line}" for line in lines)


def _terms(text: str) -> list[str]:
    found: list[str] = []
    for w in re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z_][A-Za-z0-9_]{2,}", text or ""):
        if w in {"客户", "问题", "图片消息", "怎么", "如何", "配置"}:
            continue
        found.append(w)
    extra = ["sleep", "wake", "gpio", "pwr", "ble", "uart", "ota", "flash"]
    for e in extra:
        if e in (text or "").lower():
            found.append(e)
    out: list[str] = []
    seen: set[str] = set()
    for item in found:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= 8:
            break
    return out


def _rg(root: Path, term: str, limit: int) -> list[str]:
    try:
        proc = subprocess.run(
            [
                "rg",
                "-n",
                "--max-count",
                "3",
                "-i",
                "-g",
                "!__pycache__",
                "-g",
                "!.git",
                "-g",
                "!build",
                "-g",
                "!output",
                term,
                str(root),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        if proc.returncode not in (0, 1):
            return []
        return [line[:220] for line in proc.stdout.splitlines()[:limit]]
    except Exception:
        return []


def _clean_path(raw: str) -> str:
    text = raw.strip().strip('"').strip("'")
    if text.lower().startswith("file:///"):
        text = text[8:].replace("/", "\\")
    return os.path.expandvars(os.path.expanduser(text))


def _suggest_existing_dirs(path: str) -> list[str]:
    try:
        target = Path(path)
        parent = target.parent
        if not parent.is_dir():
            return []
        import difflib

        dirs = [p for p in parent.iterdir() if p.is_dir()]
        names = [p.name for p in dirs]
        matches = difflib.get_close_matches(target.name, names, n=3, cutoff=0.55)
        return [str((parent / name).resolve()) for name in matches]
    except Exception:
        return []
