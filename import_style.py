"""导入聊天记录并生成说话风格 profile。用法见 style_data/README.txt"""
from __future__ import annotations

import argparse
import sys

import yaml

from env_loader import load_local_env
from text_encoding import load_yaml_config
from style_profile import StyleLearner

load_local_env()


def main() -> int:
    parser = argparse.ArgumentParser(description="从聊天记录学习你的说话风格")
    parser.add_argument(
        "files",
        nargs="*",
        help="聊天记录文件路径；不填则扫描 style_data/imports/",
    )
    parser.add_argument("--status", action="store_true", help="仅查看当前风格状态")
    args = parser.parse_args()

    cfg = load_yaml_config("config.yaml")
    learner = StyleLearner(cfg)

    if args.status:
        print(learner.status_text())
        return 0

    if not learner.enabled:
        print("[WARN] 请在 config.yaml 设置 style_learning.enabled: true")
        return 1

    if args.files:
        count, msg = learner.import_paths(args.files)
    else:
        count, msg = learner.rebuild_from_imports()

    print(msg)
    return 0 if count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
