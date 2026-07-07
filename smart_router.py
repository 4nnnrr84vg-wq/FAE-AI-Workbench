"""智能路由：判断关键词库答复是否合适，不合适则转本地检索 / AI。"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from keyword_learning import extract_keywords

if TYPE_CHECKING:
    from model_client import ModelClient


class SmartRouter:
    def __init__(self, cfg: dict, model: ModelClient | None = None):
        sr = cfg.get("smart_routing", {})
        self.enabled = bool(sr.get("enabled", True))
        self.min_confidence = float(sr.get("min_confidence", 0.55))
        self.ai_validate = bool(sr.get("ai_validate", True))
        self.trust_priority = int(sr.get("trust_priority", 94))
        self.validate_local_search = bool(sr.get("validate_local_search", True))
        skip = sr.get("skip_validate_ids", ["help_usage"])
        self.skip_validate_ids = {str(x) for x in skip}
        self.model = model

    def should_use_keyword(
        self,
        question: str,
        entry_id: str,
        reply: str,
        score: int,
        priority: int,
    ) -> tuple[bool, str]:
        if not self.enabled:
            return True, "smart_routing_off"
        if entry_id in self.skip_validate_ids:
            return True, "trusted_entry"
        if entry_id.startswith("cust_"):
            return True, "customer_xlsx"

        # 自動學習的條目如果關鍵字品質差，直接拒絕（避免重複被拒）
        # 门槛从 60 降到 40，避免误杀有用的旧条目
        if entry_id.startswith("auto_"):
            if priority < 40:
                return False, "auto_learned_low_quality"

        if priority >= self.trust_priority:
            return True, f"high_priority({priority})"

        conf, note = self._heuristic_confidence(question, reply, entry_id, score)
        if conf >= 0.82:
            return True, f"heuristic_ok({conf:.2f})"

        if self.ai_validate and self._can_ai_judge():
            use_kw, ai_note = self.model.judge_keyword_reply(question, reply)
            if use_kw:
                return True, f"ai_ok:{ai_note}"
            return False, f"ai_reject:{ai_note}"

        if conf >= self.min_confidence:
            return True, f"heuristic_ok({conf:.2f}:{note})"
        return False, f"heuristic_low({conf:.2f}:{note})"

    def should_use_local_search(self, question: str, reply: str) -> tuple[bool, str]:
        if not self.enabled or not self.validate_local_search:
            return True, "skip"
        # reference context 格式（交给 AI 整合）直接接受
        if reply.startswith("[[REFERENCE_CONTEXT]]"):
            return True, "reference_context"
        # 有 reference 資料時，給予較高信任
        if "[资料]" in reply:
            return True, "reference_hit"
        if "暂不可用" in reply[:100]:
            return False, "fallback_stub"
        conf, note = self._heuristic_confidence(question, reply, "local_search", score=50000)
        if conf < self.min_confidence:
            return False, f"low({conf:.2f}:{note})"
        if self.ai_validate and self._can_ai_judge() and conf < 0.7:
            use_kw, ai_note = self.model.judge_keyword_reply(question, reply)
            return use_kw, f"ai:{ai_note}"
        return True, f"ok({conf:.2f})"

    def prefer_ai_over_keyword(self, question: str) -> tuple[bool, str]:
        """无关键词命中时，判断是否应跳过本地检索、直接走重 AI。"""
        if not self.enabled:
            return False, "off"
        q = question.strip()
        if len(q) < 12:
            return False, "short"
        # 需要分析/对比/排障的长问题
        if re.search(r"(为什么|原理|对比|区别|排查|崩溃|死机|无法|失败|详细|完整)", q):
            if self._can_ai_judge():
                need, note = self.model.judge_route(question)
                return need, note
            return True, "heuristic_complex"
        return False, "default"

    def _can_ai_judge(self) -> bool:
        return bool(
            self.model
            and self.model.enabled
            and self.model.api_key
            and self.model.base_url
        )

    def _heuristic_confidence(
        self, question: str, reply: str, entry_id: str, score: int
    ) -> tuple[float, str]:
        q = question.strip()
        r = reply.strip()
        notes: list[str] = []

        conf = min(0.75, score / 120000.0)

        q_terms = extract_keywords(q)
        if q_terms:
            hit = sum(1 for t in q_terms if t.lower() in r.lower())
            ratio = hit / len(q_terms)
            conf += 0.25 * ratio
            if ratio < 0.25:
                notes.append("topic_mismatch")

        if re.search(r"(怎么|如何|配置|移植|步骤)", q):
            if len(r) < 120:
                conf -= 0.35
                notes.append("howto_but_short")
            elif any(k in r for k in ("移植", "步骤", "xc_pwr_", "sleep_init")):
                conf += 0.15

        if re.search(r"(浅睡|唤醒|按键|sleep|gpio)", q, re.I):
            if "uvprojx" in r and not any(
                k in r for k in ("移植", "xc_pwr_", "Sleep_Demo", "sleep.c", "配置")
            ):
                conf -= 0.45
                notes.append("path_only")

        if entry_id.startswith("ble_periph_lightsleep") and re.search(
            r"(浅睡|唤醒|按键)", q
        ):
            conf += 0.12

        if entry_id == "ble_peripheral" and re.search(r"(浅睡|唤醒|配置|怎么)", q):
            conf -= 0.4
            notes.append("peripheral_too_generic")

        conf = max(0.0, min(1.0, conf))
        return conf, ",".join(notes) or "ok"
