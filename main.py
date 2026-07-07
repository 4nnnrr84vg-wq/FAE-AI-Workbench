from __future__ import annotations

import os
import shutil
import sys

from text_encoding import FILE_ENCODING, load_yaml_config

from env_loader import load_local_env

load_local_env()

from bot_core import MessageBot
from local_manual import run_local

try:
    from wechat_pc_client import WeChatPcClient
except ImportError:
    WeChatPcClient = None  # type: ignore

try:
    from wecom_server import run_wecom_server
except ImportError:
    run_wecom_server = None  # type: ignore


def _normalize_config(cfg: dict) -> dict:
    """
    兼容两种 config.yaml 写法：
    - 标准：model_api / smart_routing 等在顶层（与 config.example.yaml 一致）
    - 误写：上述块嵌套在 bot: 下
    """
    bot = cfg.get("bot")
    if not isinstance(bot, dict):
        return cfg
    hoist = (
        "model_api",
        "clipboard",
        "smart_routing",
        "keyword_learning",
        "reference_learning",
        "correction_learning",
        "style_learning",
        "files",
        "vision",
        "customer_qa",
        "wecom",
        "wechat_pc",
    )
    for key in hoist:
        nested = bot.get(key)
        if not isinstance(nested, dict):
            continue
        top = cfg.get(key)
        if not isinstance(top, dict) or not top:
            cfg[key] = nested
    return cfg


def load_config() -> dict:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(base_dir, "config.yaml")
    if not os.path.exists(cfg_path):
        shutil.copy(os.path.join(base_dir, "config.example.yaml"), cfg_path)
        print("[INFO] 已自动生成 config.yaml，请填写参数后重启。")
    return _normalize_config(load_yaml_config(cfg_path))


class WeChatPcBot:
    """完整版：关键词 + AI + 风格学习 + 自动发微信。"""

    def __init__(self, cfg: dict):
        bot_cfg = cfg.get("bot", {})
        wx_cfg = cfg.get("wechat_pc", {})
        sl_cfg = cfg.get("style_learning", {})
        self.poll_interval = float(bot_cfg.get("poll_interval_sec", 2))
        self.client = WeChatPcClient(
            bot_cfg.get("allowed_chats", []),
            retry_interval_sec=int(bot_cfg.get("wechat_retry_interval_sec", 5)),
            wechat_ads=bool(bot_cfg.get("wechat_ads", False)),
            ignore_self=bool(wx_cfg.get("ignore_self", True)),
            listen_mode=str(wx_cfg.get("listen_mode", "callback")),
            my_nicknames=sl_cfg.get("my_names", []),
        )
        self.core = MessageBot(cfg, sender=self.client)

    def run(self) -> None:
        mode = self.client.listen_mode
        print(f"[INFO] 个人微信自动回复（wechat_pc / {mode}）")
        if mode == "poll":
            self._run_poll()
        else:
            self.client.run(self.core.handle_message)

    def _run_poll(self) -> None:
        while True:
            for msg in self.client.fetch_messages():
                self.core.handle_message(msg)
            import time

            time.sleep(self.poll_interval)


if __name__ == "__main__":
    config = load_config()
    mode = str(config.get("bot", {}).get("mode", "local")).lower()
    if mode == "local":
        run_local(config)
    elif mode == "wecom":
        if run_wecom_server is None:
            print("[ERROR] wecom 模式需要 flask/wechatpy")
            sys.exit(1)
        run_wecom_server(config)
    elif mode == "wechat_pc":
        if WeChatPcClient is None:
            print("[ERROR] wechat_pc 需要 wxauto4，请改用 bot.mode=local + local_mode=clipboard")
            sys.exit(1)
        WeChatPcBot(config).run()
    else:
        print(f"[ERROR] 未知 bot.mode={mode}，请使用 local / wecom / wechat_pc")
