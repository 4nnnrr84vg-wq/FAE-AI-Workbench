"""用户实时修正聊天机器人回复风格与内容的模块。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from text_encoding import read_text, write_text


def parse_rule_line(text: str) -> tuple[str, str] | None:
    """解析一行修正指令，返回 (问题关键词, 回复要求)。"""
    text = (text or "").strip()
    if not text or text.startswith("#"):
        return None

    if "对于" in text and "问题" in text:
        q_part = text.split("对于", 1)[1].split("问题", 1)[0].strip()
        if not q_part:
            return None
        for sep in ("回复要", "回答要", "回复应", "回答应", "回复", "回答"):
            if sep in text:
                instr = text.split(sep, 1)[-1].strip(" ：:，,")
                if instr:
                    return q_part, instr
        return q_part, text

    m = re.match(r"^(?:/fix|fix)\s*[:：]?\s*(.+?)\s*(?:\||=>|->)\s*(.+)$", text, re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    m = re.match(r"^(.+?)\s*(?:\||=>|->)\s*(.+)$", text)
    if m and len(m.group(1)) >= 2 and len(m.group(2)) >= 4:
        return m.group(1).strip(), m.group(2).strip()

    return None


@dataclass
class CorrectionRule:
    """单条用户修正规则"""
    question: str          # 用户问的问题关键词或原文
    instruction: str       # 用户给的修正指示（"要先说结论"、"语气要简洁" 等）
    priority: int = 80     # 优先级，数字越大越优先注入 prompt


class CorrectionLearner:
    def __init__(self, cfg: dict, base_dir: str | None = None):
        cl = cfg.get("correction_learning", {})
        self.enabled = bool(cl.get("enabled", True))
        root = base_dir or str(Path(__file__).resolve().parent)
        data_dir = Path(root) / cl.get("data_dir", "correction_data")
        self.rules_file = data_dir / "corrections.json"
        data_dir.mkdir(parents=True, exist_ok=True)
        self.rules: list[CorrectionRule] = []
        self._load()

    def _load(self) -> None:
        if not self.rules_file.is_file():
            return
        try:
            data = json.loads(read_text(self.rules_file))
            self.rules = [
                CorrectionRule(
                    question=str(item.get("question", "")),
                    instruction=str(item.get("instruction", "")),
                    priority=int(item.get("priority", 80)),
                )
                for item in data
            ]
        except Exception:
            self.rules = []

    def _save(self) -> None:
        data = [
            {"question": r.question, "instruction": r.instruction, "priority": r.priority}
            for r in self.rules
        ]
        write_text(self.rules_file, json.dumps(data, ensure_ascii=False, indent=2))

    def add_rule(self, question: str, instruction: str, priority: int = 80) -> None:
        """新增一条修正规则"""
        self.rules.append(CorrectionRule(question=question, instruction=instruction, priority=priority))
        # 简单去重：保留最新的一条
        seen = {}
        for r in self.rules:
            key = (r.question.strip().lower(), r.instruction.strip().lower())
            seen[key] = r
        self.rules = list(seen.values())
        self.rules.sort(key=lambda x: -x.priority)
        self._save()

    def try_add_line(self, text: str) -> str:
        """解析一行文本并添加规则，成功返回提示语，失败返回空字符串。"""
        parsed = parse_rule_line(text)
        if not parsed:
            return ""
        q, instr = parsed
        self.add_rule(q, instr)
        return f"[OK] 已记录: 问「{q}」→ {instr}"

    def build_prompt_addon(self) -> str:
        """生成要注入 AI prompt 的修正指示"""
        if not self.enabled or not self.rules:
            return ""
        lines = ["【用户特别指定的回复方式（必须严格遵守）】"]
        for r in self.rules[:6]:  # 最多取前 6 条，避免 prompt 太长
            q = r.question[:40]
            lines.append(f"- 问到「{q}」相关问题时：{r.instruction}")
        lines.append("以上规则优先级高于一般风格学习，请严格按照用户指示回复。")
        return "\n".join(lines)

    def status_text(self) -> str:
        if not self.rules:
            return "目前没有任何修正规则。"
        lines = [f"已记录 {len(self.rules)} 条修正规则："]
        for r in self.rules[:5]:
            lines.append(f"  • 问「{r.question[:30]}」→ {r.instruction[:40]}")
        return "\n".join(lines)