"""从聊天记录学习用户说话风格，并注入到 AI 提示词。"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from text_encoding import FILE_ENCODING, read_text, write_text


@dataclass
class StyleProfile:
    my_names: list[str] = field(default_factory=list)
    message_count: int = 0
    avg_length: float = 0.0
    summary: str = ""
    habits: list[str] = field(default_factory=list)
    examples: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "my_names": self.my_names,
            "message_count": self.message_count,
            "avg_length": self.avg_length,
            "summary": self.summary,
            "habits": self.habits,
            "examples": self.examples,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StyleProfile":
        return cls(
            my_names=list(data.get("my_names", [])),
            message_count=int(data.get("message_count", 0)),
            avg_length=float(data.get("avg_length", 0)),
            summary=str(data.get("summary", "")),
            habits=list(data.get("habits", [])),
            examples=list(data.get("examples", [])),
        )


class StyleLearner:
    def __init__(self, cfg: dict, base_dir: str | None = None):
        sl = cfg.get("style_learning", {})
        self.enabled = bool(sl.get("enabled", False))
        self.my_names = [str(x).strip() for x in sl.get("my_names", []) if str(x).strip()]
        self.max_examples = int(sl.get("max_examples", 12))
        self.max_messages = int(sl.get("max_messages_scan", 8000))
        root = base_dir or os.path.dirname(os.path.abspath(__file__))
        profile_dir = str(sl.get("profile_dir", "style_data"))
        self.data_dir = Path(root) / profile_dir
        self.imports_dir = self.data_dir / "imports"
        self.profile_path = self.data_dir / "profile.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.imports_dir.mkdir(parents=True, exist_ok=True)

    def load_profile(self) -> StyleProfile | None:
        if not self.profile_path.is_file():
            return None
        try:
            data = json.loads(read_text(self.profile_path))
            return StyleProfile.from_dict(data)
        except (json.JSONDecodeError, OSError):
            return None

    def save_profile(self, profile: StyleProfile) -> None:
        write_text(
            self.profile_path,
            json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        )

    def build_prompt_addon(self) -> str:
        if not self.enabled:
            return ""
        profile = self.load_profile()
        if not profile or profile.message_count < 3:
            return ""
        lines = [
            "【说话风格】请模仿用户一贯的语气与用词习惯回复，不要写成客服腔。",
            f"风格摘要：{profile.summary}",
        ]
        if profile.habits:
            lines.append("习惯：" + "；".join(profile.habits[:8]))
        if profile.examples:
            lines.append("参考对话（用户=提问方，我=你要模仿的口吻）：")
            for ex in profile.examples[: self.max_examples]:
                u = ex.get("other", "").strip()
                m = ex.get("me", "").strip()
                if u and m:
                    lines.append(f"对方：{u}")
                    lines.append(f"我：{m}")
        lines.append("回答时保持与技术内容准确，但表达方式贴近上述「我」的写法。")
        return "\n".join(lines)

    def import_paths(self, paths: Iterable[str]) -> tuple[int, str]:
        if not self.my_names:
            return 0, "请先在 config.yaml 的 style_learning.my_names 填写你的昵称（可多个）"

        my_msgs: list[str] = []
        pairs: list[tuple[str, str]] = []
        pending_other = ""

        for path in paths:
            text = read_text(path, errors="ignore")
            for speaker, content in self._parse_lines(text):
                if len(my_msgs) >= self.max_messages:
                    break
                if self._is_me(speaker):
                    content = content.strip()
                    if not content or len(content) < 2:
                        continue
                    my_msgs.append(content)
                    if pending_other:
                        pairs.append((pending_other, content))
                        pending_other = ""
                else:
                    if content.strip():
                        pending_other = content.strip()

        if len(my_msgs) < 3:
            return 0, f"识别到的本人消息过少（{len(my_msgs)} 条），请检查 my_names 或导出格式"

        profile = self._build_profile(my_msgs, pairs)
        self.save_profile(profile)
        return profile.message_count, (
            f"已学习 {profile.message_count} 条消息，"
            f"示例对话 {len(profile.examples)} 组 → {self.profile_path}"
        )

    def rebuild_from_imports(self) -> tuple[int, str]:
        files = sorted(
            p
            for p in self.imports_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".txt", ".log", ".csv", ".json"}
        )
        if not files:
            return 0, f"请将聊天记录放入 {self.imports_dir}"
        return self.import_paths(str(p) for p in files)

    def status_text(self) -> str:
        if not self.enabled:
            return "风格学习未启用（style_learning.enabled=false）"
        profile = self.load_profile()
        if not profile:
            return (
                f"尚未导入风格。把聊天记录放到 {self.imports_dir}，"
                "运行 import_style.bat 或发送 /style 重建"
            )
        return (
            f"已学习 {profile.message_count} 条，示例 {len(profile.examples)} 组\n"
            f"摘要：{profile.summary}\n"
            f"文件：{self.profile_path}"
        )

    def _is_me(self, speaker: str) -> bool:
        s = speaker.strip()
        if not s:
            return False
        for name in self.my_names:
            if name == s or name in s or s in name:
                return True
        return False

    def _parse_lines(self, text: str) -> list[tuple[str, str]]:
        """解析多种常见导出格式，产出 (说话人, 内容)。"""
        rows: list[tuple[str, str]] = []
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            m = re.match(r"^(.+?)[：:]\s*(.+)$", line)
            if m and len(m.group(2)) > 0:
                rows.append((m.group(1).strip(), m.group(2).strip()))
                i += 1
                continue

            m = re.match(
                r"^(.+?)\s+(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)",
                line,
            )
            if m:
                speaker = m.group(1).strip()
                body: list[str] = []
                i += 1
                while i < len(lines):
                    nxt = lines[i].strip()
                    if not nxt:
                        i += 1
                        break
                    if self._looks_like_header(nxt):
                        break
                    body.append(nxt)
                    i += 1
                if body:
                    rows.append((speaker, "\n".join(body)))
                continue

            m = re.match(r"^\[([^\]]+)\]\s*(.*)$", line)
            if m:
                speaker = m.group(1).strip()
                first = m.group(2).strip()
                body = [first] if first else []
                i += 1
                while i < len(lines):
                    nxt = lines[i].strip()
                    if not nxt or self._looks_like_header(nxt):
                        break
                    body.append(nxt)
                    i += 1
                if body:
                    rows.append((speaker, "\n".join(body)))
                continue

            if line.startswith("{") and line.endswith("}"):
                try:
                    obj = json.loads(line)
                    sp = str(obj.get("sender") or obj.get("nick") or obj.get("name", ""))
                    ct = str(obj.get("content") or obj.get("text") or obj.get("msg", ""))
                    if sp and ct:
                        rows.append((sp, ct))
                except json.JSONDecodeError:
                    pass
                i += 1
                continue

            i += 1
        return rows

    def _looks_like_header(self, line: str) -> bool:
        if re.match(r"^.+?[：:].+$", line) and len(line) < 120:
            return True
        if re.match(r"^.+?\s+\d{4}[-/年]", line):
            return True
        if line.startswith("[") and "]" in line[:40]:
            return True
        return False

    def _build_profile(
        self, my_msgs: list[str], pairs: list[tuple[str, str]]
    ) -> StyleProfile:
        lengths = [len(m) for m in my_msgs]
        avg_len = sum(lengths) / max(len(lengths), 1)

        starters = Counter()
        for m in my_msgs:
            head = m[:2] if len(m) >= 2 else m
            if head:
                starters[head] += 1

        habits: list[str] = []
        if avg_len < 25:
            habits.append("偏短句，少说废话")
        elif avg_len > 80:
            habits.append("习惯写较长、带细节")
        else:
            habits.append("中等长度，信息密度适中")

        punct = "".join(my_msgs)
        if punct.count("～") + punct.count("~") > len(my_msgs) * 0.1:
            habits.append("常用波浪线语气")
        if punct.count("...") + punct.count("…") > len(my_msgs) * 0.08:
            habits.append("常用省略号")
        if re.search(r"[\U0001F300-\U0001FAFF]", punct):
            habits.append("偶尔用表情符号")
        top = [w for w, _ in starters.most_common(3)]
        if top:
            habits.append("常见开头：" + "、".join(f"「{t}」" for t in top))

        summary = (
            f"共 {len(my_msgs)} 条消息，平均约 {avg_len:.0f} 字；"
            + (habits[0] if habits else "口语化")
        )

        examples: list[dict[str, str]] = []
        seen: set[str] = set()
        for other, me in pairs:
            key = me[:40]
            if key in seen or len(me) < 4:
                continue
            seen.add(key)
            examples.append(
                {
                    "other": other[:200],
                    "me": me[:400],
                }
            )
            if len(examples) >= self.max_examples:
                break

        if len(examples) < 3:
            for m in my_msgs:
                if len(examples) >= min(6, self.max_examples):
                    break
                key = m[:40]
                if key in seen:
                    continue
                seen.add(key)
                examples.append({"other": "（无上下文）", "me": m[:400]})

        return StyleProfile(
            my_names=self.my_names,
            message_count=len(my_msgs),
            avg_length=avg_len,
            summary=summary,
            habits=habits,
            examples=examples,
        )
