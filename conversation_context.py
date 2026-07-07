"""簡單的對話上下文記憶（支援追問）。"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque


@dataclass
class Turn:
    question: str
    answer: str


class ConversationContext:
    def __init__(self, max_turns: int = 5):
        self.max_turns = max_turns
        self.turns: Deque[Turn] = deque(maxlen=max_turns)

    def add_turn(self, question: str, answer: str) -> None:
        q = (question or "").strip()
        a = (answer or "").strip()
        if not q or not a:
            return
        self.turns.append(Turn(q, a))

    def get_context_text(self, max_chars: int = 1200) -> str:
        if not self.turns:
            return ""
        lines: list[str] = ["【最近對話參考】"]
        total = 0
        for t in reversed(self.turns):
            block = f"用戶：{t.question}\n助理：{t.answer}\n"
            if total + len(block) > max_chars:
                break
            lines.append(block)
            total += len(block)
        return "\n".join(reversed(lines))

    def clear(self) -> None:
        self.turns.clear()

    def size(self) -> int:
        return len(self.turns)
