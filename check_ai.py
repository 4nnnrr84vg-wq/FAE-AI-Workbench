"""一键检查 AI 是否可用。

推荐: 双击 check_ai.bat，脚本会优先使用项目虚拟环境，
不可用时自动退到本机 Python（如 D:\\python\\python.exe）。
"""
from __future__ import annotations

import os
import sys

try:
    import yaml
except ModuleNotFoundError:
    print(
        "[ERROR] 缺少 PyYAML。请用虚拟环境运行：\n"
        "  cd D:\\wechat_bot\\wechat_bot\n"
        "  D:\\python\\python.exe -m pip install pyyaml\n"
        "或双击 check_ai.bat，让脚本选择可用 Python。"
    )
    sys.exit(1)

from env_loader import load_local_env
from text_encoding import load_yaml_config

load_local_env()


def main() -> int:
    cfg = load_yaml_config("config.yaml")
    from model_client import ModelClient

    m = ModelClient(cfg)
    print("model_api_enabled:", m.enabled)
    print("api_key:", "已设置" if m.api_key else "未设置")
    print("base_url:", m.base_url)
    print("model:", m.model)
    if not m.enabled:
        print("\n请在 config.yaml 中设置 model_api.enabled=true")
        return 1
    if not m.api_key:
        print("\n请双击 set_api_key.bat 设置 DEEPSEEK_API_KEY 后重试")
        return 1
    print("\n测试问题: 浅睡io唤醒怎么配置")
    print("（约 5~30 秒）\n")
    text = m.generate_reply("浅睡io唤醒怎么配置", prefer_model_api=True)
    if text:
        print("--- 回复 ---")
        print(text[:2000])
        return 0
    print("失败:", m.last_error)
    print("\n请检查 DEEPSEEK_API_KEY、base_url、网络连接或模型名。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
