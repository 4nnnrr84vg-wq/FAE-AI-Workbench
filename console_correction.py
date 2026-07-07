"""运行界面直接输入修正规则（与 Ctrl+Q 热键并行）。"""
from __future__ import annotations

import sys
import threading

from correction_learner import CorrectionLearner, parse_rule_line


def run_correction_interactive(learner: CorrectionLearner) -> None:
    """交互式修正模式（在控制台里输入）。"""
    print("\n=== 修正模式（控制台）===")
    print("示例：对于 蓝牙连接标志位 问题，回复要先说 slave_connected，再说在哪个文件")
    print("或一行写法：蓝牙连接标志位 | 先说结论，再说 app_task.c 里怎么置位")
    print("输入 q / 退出 结束本模式（bot 继续运行）\n")

    while True:
        try:
            user_input = input("修正> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[INFO] 已退出修正模式")
            break
        if not user_input:
            continue
        if user_input.lower() in ("退出", "q", "quit", "exit"):
            print("[INFO] 已退出修正模式")
            break

        parsed = parse_rule_line(user_input)
        if parsed:
            q, instr = parsed
            learner.add_rule(q, instr)
            print(f"[OK] 已记录: 问「{q}」→ {instr}")
            continue

        if user_input in ("列表", "list", "status"):
            print(learner.status_text())
            continue

        print("[WARN] 未识别格式。请用：对于 XXX 问题，回复要 YYY  或  XXX | YYY")


def _print_console_help() -> None:
    print("[INFO] Console commands (type in this window anytime):")
    print("  - 对于 蓝牙连接标志位 问题，回复要先说结论再说文件")
    print("  - 蓝牙连接标志位 | 回复要简洁，只说 slave_connected")
    print("  - /fix          enter interactive correction mode")
    print("  - /fix list     show saved correction rules")
    print("  - /file list    show registered file mappings")
    print("  - /file map XC6517 E:/docs/XC6517.pdf   register a file")


def start_console_input_thread(bot) -> None:
    """后台读取控制台输入，与热键循环并行。"""

    def _worker() -> None:
        learner: CorrectionLearner = bot.correction
        _print_console_help()
        while True:
            try:
                line = sys.stdin.readline()
            except Exception:
                break
            if not line:
                break
            text = line.strip()
            if not text:
                continue

            low = text.lower()
            if low in ("/fix", "/修正", "修正", "fix"):
                run_correction_interactive(learner)
                continue
            if low in ("/fix list", "/修正 list", "/修正列表", "修正列表", "list rules"):
                print(learner.status_text())
                continue
            if low in ("/help", "help", "/fix help"):
                _print_console_help()
                continue

            if text.startswith("/file"):
                resolver = bot.router.file_resolver
                result = resolver.resolve_or_message(text)
                if result.get("type") == "text":
                    print(result.get("content", ""))
                elif result.get("type") == "file":
                    print(f"[OK] {result.get('notice', result.get('path', ''))}")
                continue

            parsed = parse_rule_line(text)
            if parsed:
                q, instr = parsed
                learner.add_rule(q, instr)
                print(f"[OK] 已记录: 问「{q}」→ {instr}")
                continue

            if text.startswith("/"):
                print("[WARN] 未知命令。/fix 修正规则，/file map 注册文件，/help 帮助")
            else:
                print("[WARN] 未识别。示例: 对于 XXX 问题，回复要 YYY  或  XXX | YYY")

    t = threading.Thread(target=_worker, name="console-correction", daemon=True)
    t.start()
