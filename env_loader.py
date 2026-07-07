"""从 tools/wechat_bot/.env 加载环境变量（不提交 git）。"""
from __future__ import annotations

import os

from text_encoding import open_text


def load_local_env(base_dir: str | None = None) -> None:
    root = base_dir or os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(root, ".env")
    if not os.path.isfile(path):
        return
    with open_text(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
