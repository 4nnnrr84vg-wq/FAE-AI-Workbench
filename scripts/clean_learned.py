"""Remove polluted entries from keyword_data/learned.yaml."""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from text_encoding import load_yaml_config, write_text  # noqa: E402

LEARNED_PATH = _ROOT / "keyword_data" / "learned.yaml"

BAD_REPLY_MARKERS = (
    "[[REFERENCE_CONTEXT]]",
    "已从 reference/documents/",
    "无法自动整合",
    "请配置 model_api",
    "base_url / api_key",
    "memtitle",
    "memitem",
    "只用一段话",
    "模型接口暂不可用",
    "以下为仓库内检索摘要",
)

BAD_REPLY_RE = re.compile(
    r"检索词：.+问题：|&#9670;|<h2\s+class=|<tr\s+class=[\"']memitem",
    re.I | re.S,
)


def is_polluted(entry: dict) -> bool:
    reply = str(entry.get("reply") or "")
    if any(m in reply for m in BAD_REPLY_MARKERS):
        return True
    if BAD_REPLY_RE.search(reply):
        return True
    if "测试回复内容" in reply and len(reply) < 100:
        return True
    for kw in entry.get("keywords") or []:
        if not isinstance(kw, str):
            continue
        if len(kw) > 120 and ("app_task" in kw or "GAPC_" in kw or "slave_connected" in kw):
            return True
    return False


def main() -> None:
    data = load_yaml_config(LEARNED_PATH)
    entries = list(data.get("entries") or [])
    kept = [e for e in entries if not is_polluted(e)]
    removed = [e.get("id", "?") for e in entries if is_polluted(e)]

    payload = {
        "entries": kept,
        "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    write_text(LEARNED_PATH, yaml.dump(payload, allow_unicode=True, default_flow_style=False, sort_keys=False, width=120))

    print(f"before={len(entries)} after={len(kept)} removed={len(removed)}")
    for rid in removed:
        print(f"  - {rid}")


if __name__ == "__main__":
    main()
