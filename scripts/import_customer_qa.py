"""导入桌面「客户问题汇总」Excel 到关键词库。"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from customer_qa_import import import_customer_xlsx, parse_customer_xlsx
from main import load_config
from router import Router


def main() -> None:
    parser = argparse.ArgumentParser(description="导入客户问题汇总 xlsx 到 learned.yaml")
    parser.add_argument(
        "xlsx",
        nargs="?",
        default=r"c:\Users\Administrator\Desktop\客户问题汇总(已自动还原).xlsx",
        help="Excel 路径",
    )
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    parser.add_argument("--list", action="store_true", help="列出解析结果")
    args = parser.parse_args()

    cfg = load_config()
    if args.list:
        items = parse_customer_xlsx(args.xlsx)
        print(f"共解析 {len(items)} 条（含无答案）")
        for it in items[:20]:
            ans = (it["answer"] or "")[:50]
            print(f"[{it['sheet']}] {it['question'][:50]} => {ans}")
        with_ans = sum(1 for x in items if (x.get("answer") or "").strip())
        print(f"有答案: {with_ans}")
        return

    added, skipped, msg = import_customer_xlsx(cfg, args.xlsx, dry_run=args.dry_run)
    print(msg)
    if not args.dry_run and added:
        router = Router(cfg)
        router.reload_keywords()
        print(f"关键词库已重载，当前 {router.keyword_lib.count()} 条")


if __name__ == "__main__":
    main()
