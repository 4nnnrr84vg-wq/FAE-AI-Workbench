from __future__ import annotations

import os

from keyword_lib import KeywordLibrary
from file_resolver import FileResolver


class Router:
    def __init__(self, config: dict):
        self.config = config
        self.default_reply = config.get("bot", {}).get("default_reply", "收到。")
        files_cfg = config.get("files", {})
        self.command_prefix = files_cfg.get("command_prefix", "/file")
        self.file_map = files_cfg.get("mapping", {})
        sl = config.get("style_learning", {})
        self.style_prefix = str(sl.get("command_prefix", "/style"))
        kl = config.get("keyword_learning", {})
        self.keyword_cmd_prefix = str(kl.get("command_prefix", "/keyword"))
        cl = config.get("correction_learning", {})
        self.correction_cmd_prefix = str(cl.get("command_prefix", "/修正"))
        rl = config.get("reference_learning", {})
        self.reference_cmd_prefix = str(rl.get("command_prefix", "/reference"))
        self.keyword_lib = KeywordLibrary(config)
        self.file_resolver = FileResolver(config)
        self.keyword_replies = dict(
            config.get("bot", {}).get("keyword_replies", {}) or {}
        )
        self.keyword_replies.update(
            config.get("wechat_pc", {}).get("keyword_replies", {}) or {}
        )

    def reload_keywords(self) -> None:
        self.keyword_lib.reload(self.config)
        self.file_resolver.reload(self.config)

    def route(self, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            return {"type": "none"}

        if text.startswith(self.style_prefix):
            return {"type": "style", "arg": text[len(self.style_prefix) :].strip()}

        if text.startswith(self.keyword_cmd_prefix):
            return {"type": "keyword_cmd", "arg": text[len(self.keyword_cmd_prefix) :].strip()}

        if text.startswith(self.correction_cmd_prefix):
            return {"type": "correction_cmd", "arg": text[len(self.correction_cmd_prefix) :].strip()}

        if text.startswith(self.reference_cmd_prefix):
            return {"type": "reference_cmd", "arg": text[len(self.reference_cmd_prefix) :].strip()}

        for kw, reply in self.keyword_replies.items():
            if kw and kw in text:
                return {"type": "text", "content": str(reply), "reason": "keyword"}

        hit = self.keyword_lib.match(text)
        if hit:
            return {
                "type": "keyword_candidate",
                "content": hit["reply"],
                "entry_id": hit["id"],
                "score": hit["score"],
                "priority": hit["priority"],
                "reason": f"keyword_lib:{hit['id']}",
            }

        if text.startswith(self.command_prefix):
            return self.file_resolver.resolve_or_message(text)

        file_hit = self.file_resolver.try_resolve(text)
        if file_hit:
            return {"type": "file", **file_hit}

        for key in self.file_map.keys():
            if key in text:
                return self._file_action(key)

        return {"type": "nlp_or_default"}
    def _file_action(self, key: str) -> dict:
        path = self.file_map.get(key)
        if not path:
            return {"type": "text", "content": f"未配置文件：{key}"}
        if not os.path.exists(path):
            return {"type": "text", "content": f"文件不存在：{path}"}
        return {"type": "file", "key": key, "path": path}
