from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import requests

from correction_learner import CorrectionLearner
from local_search import build_local_reply
from style_profile import StyleLearner

logger = logging.getLogger(__name__)

SIMPLIFIED_CN_INSTRUCTION = (
    "必须用简体中文回复。"
    "回答只用一段话，尽量短，像同事在微信里快速解释问题一样。"
    "不要列点、不要贴代码、不要解释太多背景，直接说重点。"
)


def _cfg_section(root: dict, key: str) -> dict:
    """读取配置块：优先顶层，其次 bot 下（兼容误嵌套）。"""
    sec = root.get(key)
    if isinstance(sec, dict) and sec:
        return sec
    bot = root.get("bot")
    if isinstance(bot, dict):
        nested = bot.get(key)
        if isinstance(nested, dict):
            return nested
    return {}


def _api_key_from_cfg(section: dict, default_env: str) -> str:
    direct = str(section.get("api_key", "") or "").strip()
    if direct and direct not in {"YOUR_API_KEY", "replace-with-your-api-key"}:
        return direct
    env_name = str(section.get("api_key_env", default_env) or default_env).strip()
    return str(os.environ.get(env_name, "") or "").strip()


class ModelClient:
    """OpenAI-compatible model client with local knowledge-base fallback."""

    def __init__(self, root_config: dict):
        api_cfg = _cfg_section(root_config, "model_api")
        self.enabled = bool(api_cfg.get("enabled", False))
        self.base_url = str(api_cfg.get("base_url", "")).rstrip("/")
        self.api_key = _api_key_from_cfg(api_cfg, "DEEPSEEK_API_KEY")
        self.model = str(api_cfg.get("model", "deepseek-chat"))
        self.timeout_sec = int(api_cfg.get("timeout_sec", 30))
        self.system_prompt = str(api_cfg.get("system_prompt", "你是一个微信助理。"))
        self.workspace = str(
            api_cfg.get("workspace")
            or root_config.get("workspace")
            or Path(__file__).resolve().parent
        )
        self.fallback_local_search = bool(api_cfg.get("fallback_local_search", True))

        self.last_error = ""
        self.last_usage: dict = {}
        self.style = StyleLearner(root_config)
        self.correction = CorrectionLearner(root_config)

        vision_cfg = _cfg_section(root_config, "vision")
        self.vision_enabled = bool(vision_cfg.get("enabled", True))
        self.vision_model = str(vision_cfg.get("model", "") or "").strip()
        self.vision_max_images = int(vision_cfg.get("max_images", 4))
        self.vision_prefer_model_api = bool(vision_cfg.get("prefer_model_api", True))

    def _style_addon(self) -> str:
        return self.style.build_prompt_addon()

    def _correction_addon(self) -> str:
        return self.correction.build_prompt_addon()

    def generate_reply(
        self,
        user_text: str,
        context_text: str = "",
        prefer_model_api: bool = False,
    ) -> str:
        self.last_error = ""
        self.last_usage = {}

        if self.enabled:
            reply = self._generate_by_openai_compatible(user_text, context_text)
            if reply:
                return reply

        if prefer_model_api:
            if not self.last_error:
                self.last_error = "model_api 未返回内容"
            return ""

        if self.fallback_local_search:
            local = build_local_reply(user_text, self.workspace)
            if local:
                print("[INFO] 已使用本地资料检索备用答复", flush=True)
                if local.startswith("[[REFERENCE_CONTEXT]]"):
                    body = local.replace("[[REFERENCE_CONTEXT]]", "").strip()
                    return (
                        "（已从 reference/documents/ 检索到相关资料，但当前未配置可用的 AI 模型，"
                        "无法自动整合成自然回答）\n\n"
                        + body
                        + "\n\n请配置 model_api.enabled=true 并提供 base_url / api_key。"
                    )
                return local

        if not self.last_error:
            self.last_error = "model_api 未返回内容，且本地检索没有命中"
        return ""

    def generate_reply_with_images(
        self,
        user_text: str,
        images: list[bytes],
        context_text: str = "",
        *,
        image_paths: list[str] | None = None,
    ) -> str:
        """图文消息：本地 OCR -> 视觉 model_api -> 纯文本 model_api/本地检索兜底。"""
        self.last_error = ""
        self.last_usage = {}
        images = [img for img in (images or []) if img][: self.vision_max_images]
        if not images:
            return self.generate_reply(user_text, context_text)

        from image_ocr import build_enriched_prompt, extract_text_from_paths

        paths = list(image_paths or [])
        ocr_text = extract_text_from_paths(paths) if paths else ""
        if ocr_text:
            preview = ocr_text.replace("\n", " ")[:60]
            print(f"[INFO] 本地 OCR 完成（{len(ocr_text)} 字）: {preview}...", flush=True)
        else:
            print("[WARN] 本地 OCR 未识别到文字（可能是纯图标/照片）", flush=True)

        enriched = build_enriched_prompt(user_text, ocr_text)

        if self.vision_enabled and self.vision_prefer_model_api and self.enabled and self.api_key:
            reply = self._generate_vision_by_openai_compatible(enriched, images, context_text)
            if reply:
                return reply

        reply = self.generate_reply(enriched, context_text)
        if reply and not self._is_ai_failure_reply(reply):
            return reply

        return self._build_image_fallback_reply(ocr_text, enriched, self.last_error)

    def _is_ai_failure_reply(self, reply: str) -> bool:
        low = (reply or "").lower()
        markers = ("ai 失败", "未能完成识图", "未配置可用的 ai", "model_api 未返回")
        return any(m in low for m in markers)

    def _build_image_fallback_reply(self, ocr_text: str, enriched: str, err: str) -> str:
        parts: list[str] = []
        if ocr_text:
            parts.append("【图片识别内容】")
            parts.append(ocr_text.strip())

        local = build_local_reply(enriched or ocr_text, self.workspace)
        if local:
            if local.startswith("[[REFERENCE_CONTEXT]]"):
                body = local.replace("[[REFERENCE_CONTEXT]]", "").strip()
                lines = [
                    ln.strip()
                    for ln in body.splitlines()
                    if ln.strip()
                    and not ln.strip().startswith("问题：")
                    and not ln.strip().startswith("检索词：")
                ]
                ref_lines = [ln for ln in lines if ln.startswith("- ") or ln.startswith("[资料]")]
                if ref_lines:
                    parts.append("\n【相关资料】")
                    parts.extend(ref_lines[:8])
            elif len(local) > 30:
                parts.append("\n【本地检索】")
                parts.append(local[:1200])

        if parts:
            if err:
                parts.append(f"\n（模型接口暂不可用，以上为本机 OCR + 资料检索结果；错误：{err[:120]}）")
            return "\n".join(parts)

        return (
            "已收到图片，但 AI 与 OCR 均未能生成有效回答。"
            f"{'OCR 未识别到文字。' if not ocr_text else ''}"
            f"{('错误：' + err[:120]) if err else ''}"
        )

    def _vision_model_name(self) -> str:
        if self.vision_model:
            return self.vision_model
        base = self.model.lower()
        if any(k in base for k in ("gpt-4o", "vision", "vl", "gemini", "claude-3")):
            return self.model
        return "gpt-4o-mini"

    def _generate_vision_by_openai_compatible(
        self,
        user_text: str,
        images: list[bytes],
        context_text: str = "",
    ) -> str:
        if not self.enabled or not self.base_url or not self.api_key:
            return ""

        import base64

        sys_content = self._system_content()
        user_parts: list[dict] = []
        prompt = user_text.strip() or "请描述并回答用户图片中的问题。"
        if context_text:
            prompt = f"{context_text}\n\n{prompt}"
        user_parts.append({"type": "text", "text": prompt})
        for img in images:
            b64 = base64.b64encode(img).decode("ascii")
            user_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                }
            )

        payload = {
            "model": self._vision_model_name(),
            "messages": [
                {"role": "system", "content": sys_content},
                {"role": "user", "content": user_parts},
            ],
            "temperature": 0.2,
        }
        try:
            print(
                f"[INFO] 视觉模型识图中（{self._vision_model_name()}，{len(images)} 张图）...",
                flush=True,
            )
            data = self._post_chat(payload, timeout=max(60, self.timeout_sec))
            reply = data["choices"][0]["message"]["content"].strip()
            self._record_usage(data)
            return reply
        except Exception as e:
            logger.warning("Vision API: %s", e)
            self.last_error = str(e)
            return ""

    def judge_keyword_reply(self, question: str, candidate_reply: str) -> tuple[bool, str]:
        """用 model_api 快速判断关键词库答复是否切题。"""
        if not self.enabled or not self.api_key or not self.base_url:
            return True, "no_model_api"

        system = (
            "你是问答路由裁判。根据用户问题和候选回复，判断候选能否直接、合理地回答用户。"
            "只输出一行 JSON：{\"use_keyword\": true/false, \"reason\": \"简短原因\"}。"
            "若候选只给工程路径但用户在问配置/原理/步骤，应 use_keyword=false。"
        )
        user = f"用户问题：{question}\n\n候选回复：\n{candidate_reply[:1500]}"
        text = self._chat_json(system, user, max_tokens=120)
        if not text:
            return True, "judge_failed"
        try:
            obj = json.loads(text)
            return bool(obj.get("use_keyword", True)), str(obj.get("reason", ""))[:80]
        except json.JSONDecodeError:
            low = text.lower()
            if "false" in low and "use_keyword" in low:
                return False, text[:80]
            return True, "parse_fallback"

    def judge_route(self, question: str) -> tuple[bool, str]:
        """判断是否应走完整 AI（而非仅本地检索）。"""
        if not self.enabled or not self.api_key:
            return False, "no_model_api"
        system = (
            "判断该问题是否需要结合代码仓库做深度技术分析。"
            "只输出 JSON：{\"need_deep_ai\": true/false, \"reason\": \"简短\"}。"
            "简单FAQ、路径查询 need_deep_ai=false；排障、原理、多文件分析 need_deep_ai=true。"
        )
        text = self._chat_json(system, f"用户问题：{question}", max_tokens=80)
        if not text:
            return False, "judge_failed"
        try:
            obj = json.loads(text)
            return bool(obj.get("need_deep_ai", False)), str(obj.get("reason", ""))[:80]
        except json.JSONDecodeError:
            return False, "parse_fallback"

    def _chat_json(self, system: str, user: str, *, max_tokens: int = 120) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        try:
            data = self._post_chat(payload, timeout=min(20, self.timeout_sec))
            raw = data["choices"][0]["message"]["content"].strip()
            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.lower().startswith("json"):
                    raw = raw[4:].strip()
            return raw
        except Exception as e:
            logger.warning("judge API: %s", e)
            return ""

    def _generate_by_openai_compatible(self, user_text: str, context_text: str = "") -> str:
        if not self.enabled or not self.base_url or not self.api_key:
            return ""

        messages = [{"role": "system", "content": self._system_content()}]
        if context_text:
            messages.append({"role": "assistant", "content": context_text})
        messages.append({"role": "user", "content": user_text})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.35 if self._style_addon() else 0.2,
        }

        try:
            data = self._post_chat(payload, timeout=self.timeout_sec)
            reply = data["choices"][0]["message"]["content"].strip()
            self._record_usage(data)
            return reply
        except Exception as e:
            logger.warning("OpenAI-compatible API: %s", e)
            err = str(e)
            if isinstance(e, requests.exceptions.ConnectTimeout):
                err = (
                    f"{err}；连接模型服务超时，通常是代理/VPN/TUN/防火墙导致终端无法访问 "
                    f"{self.base_url}"
                )
            self.last_error = err
            return ""

    def _system_content(self) -> str:
        sys_content = self.system_prompt
        if SIMPLIFIED_CN_INSTRUCTION not in sys_content:
            sys_content = f"{sys_content}\n{SIMPLIFIED_CN_INSTRUCTION}"
        addon = self._style_addon()
        if addon:
            sys_content = f"{sys_content}\n\n{addon}"
        corr = self._correction_addon()
        if corr:
            sys_content = f"{sys_content}\n\n{corr}"
        return sys_content

    def _post_chat(self, payload: dict, *, timeout: int) -> dict:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _record_usage(self, data: dict) -> None:
        usage = data.get("usage", {})
        if usage:
            self.last_usage = {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }
