"""剪贴板模式：在微信选中消息 → Ctrl+Q 复制并生成回复 → Ctrl+V 粘贴。无需 wxauto4。"""
from __future__ import annotations

import logging
import os
import time

from bot_core import MessageBot
from clipboard_payload import read_clipboard_payload
from local_manual import _check_ai_ready
from project_assistant import generate_project_reply, prompt_project_path
from toast_notify import init_toast, toast_done, toast_error, toast_file_ready, toast_generating, toast_warn
from win_clipboard import get_text, set_files, set_text
from win_hotkey import run_hotkey_loop, simulate_ctrl_c


def _process_clipboard(
    bot: MessageBot,
    default_chat: str,
    copy_reply: bool,
    min_len: int,
    state: dict,
    *,
    force: bool = False,
    force_ai: bool = False,
) -> None:
    payload = read_clipboard_payload()
    cb_cfg_full = bot.cfg.get("clipboard") or {}
    if not bool(cb_cfg_full.get("image_recognition", True)):
        payload.images = []
    text = payload.user_text()
    raw_text = (payload.text or "").strip()

    if not payload.has_content:
        print("[WARN] 剪贴板为空，请先在微信里选中消息（文字或图片）")
        toast_warn("剪贴板为空", bot.cfg)
        return
    if not payload.has_images and (not raw_text or len(raw_text) < min_len):
        print("[WARN] 剪贴板内容过短，请先在微信里选中消息")
        toast_warn("剪贴板内容过短", bot.cfg)
        return
    if payload.has_images:
        print(f"[INFO] 检测到剪贴板含 {len(payload.images)} 张图片", flush=True)

    fp = payload.fingerprint()

    if force:
        state["last_seen"] = text
    else:
        state["last_fp"] = fp
        state["last_seen"] = text

    project_path = prompt_project_path(bot.cfg, state)
    if project_path:
        toast_generating(bot.cfg)
        reply = generate_project_reply(
            bot,
            question=text,
            raw_text=raw_text,
            images=payload.images,
            project_path=project_path,
            force_ai=force_ai,
        )
    else:
        toast_generating(bot.cfg)
        if force_ai:
            print("[INFO] Ctrl+R：强制 AI 重新回答（跳过关键词库/本地检索）", flush=True)
        reply = bot.handle_message(
            {
                "chat": default_chat,
                "sender": "clipboard",
                "content": text,
                "raw_text": raw_text,
                "images": payload.images,
                "type": "mixed" if payload.has_images else "text",
                "allow_repeat": True,
                "force_ai": force_ai,
            }
        )

    file_path = getattr(bot, "last_file_path", None)
    if file_path and os.path.isfile(file_path):
        if set_files([file_path]):
            state["last_reply"] = ""
            state["last_seen"] = f"__file__:{file_path}"
            state["last_paste_time"] = time.time()
            print(f"[INFO] 文件已复制到剪贴板: {file_path}")
            print("[INFO] 在微信聊天框 Ctrl+V 即可发送文件")
            try:
                from win_hotkey import press_key
                press_key(0x11)
                press_key(0x56)
                time.sleep(0.05)
                press_key(0x56, 0x0002)
                press_key(0x11, 0x0002)
                print("[INFO] 已尝试自动粘贴文件到微信")
            except Exception as e:
                print(f"[WARN] 自动粘贴文件失败: {e}，请手动 Ctrl+V")
            toast_file_ready(bot.cfg)
        else:
            print(f"[WARN] 无法把文件放入剪贴板: {file_path}")
            toast_error("文件复制失败", bot.cfg)
        if reply:
            print(f"[INFO] {reply}")
        return

    # 保存最后一次生成的答案，供 Ctrl+W 使用
    if reply:
        state["last_reply"] = reply

    # 生成后自动把答案粘贴到当前微信聊天输入框（让答案在聊天记录中显示）
    if reply:
        try:
            set_text(reply)                    # 先把答案放到剪贴板
            # 模拟 Ctrl+V，把答案粘贴到当前微信输入框
            from win_hotkey import press_key
            press_key(0x11)      # Ctrl
            press_key(0x56)      # V
            time.sleep(0.05)
            press_key(0x56, 0x0002)
            press_key(0x11, 0x0002)
            state["last_seen"] = reply
            state["last_paste_time"] = time.time()
            print("[INFO] Answer auto-pasted to WeChat chat (visible in history)")
            toast_done(bot.cfg, preview=reply)
        except Exception as e:
            print(f"[WARN] 自动粘贴失败: {e}")
            # 降级：至少把答案留在剪贴板
            set_text(reply)
            print("[INFO] Reply copied to clipboard, please Ctrl+V manually")
            toast_done(bot.cfg, preview=reply)
    elif reply is None:
        print("[WARN] 未生成回答", flush=True)
    else:
        toast_error("未能生成有效答案", bot.cfg)


def run_clipboard_watch(cfg: dict) -> None:
    import sys
    # 強制 stdout 使用 UTF-8，確保中文正常顯示（避免 GB18030 內部字串印到 console 亂碼）
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    _check_ai_ready(cfg)

    bot_cfg = cfg.get("bot", {})
    cb_cfg = cfg.get("clipboard") or bot_cfg.get("clipboard") or {}
    min_len = int(cb_cfg.get("min_length", 2))
    copy_reply = bool(cb_cfg.get("copy_reply", True))
    copy_delay = float(cb_cfg.get("copy_delay_sec", 0.12))
    default_chat = str(bot_cfg.get("local_default_chat", "All Chats"))
    # 强制清洗，防止任何非 ASCII 字符导致 console 乱码
    try:
        default_chat = default_chat.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        if any(ord(c) > 127 for c in default_chat):
            default_chat = "All Chats"
    except Exception:
        default_chat = "All Chats"

    bot = MessageBot(cfg, sender=None)
    state = {"last_fp": "", "last_seen": get_text(), "last_reply": ""}

    init_toast(cfg)
    project_cfg = cfg.get("project_assistant") or {}
    use_project_prompt = bool(project_cfg.get("enabled", True)) and bool(
        project_cfg.get("prompt_project_path", True)
    )
    if use_project_prompt:
        print("[INFO] Project assistant prompt enabled; console correction input is disabled to avoid input conflicts.")
        print("[INFO] Press Enter at project prompt to skip project analysis and answer directly.")
    else:
        from console_correction import start_console_input_thread

        start_console_input_thread(bot)

    print("[INFO] Clipboard mode (no wxauto4 needed)")
    print(f"[INFO] Default chat: {default_chat}")
    print("[INFO] Usage: Select message → Ctrl+Q to generate (clipboard)")
    print("[INFO] Ctrl+R: force AI re-answer (skip keyword/local cache)")
    print("[INFO] Supports text + image mixed copy from WeChat")
    print("[INFO] File request (e.g. datasheet): auto copy file to clipboard")
    print("[INFO] Console: /file map XC6517 E:/path/to/file.pdf")
    print("[INFO] Double-press Ctrl+Q (Ctrl+Q+Q) to generate + auto-paste")
    print("[INFO] Ctrl+Shift+Q to exit")
    print("-" * 50)

    # 強制 stdout 使用 UTF-8，避免中文亂碼
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    DOUBLE_Q_THRESHOLD = 0.8  # 两次 Ctrl+Q 间隔 < 0.8秒 视为 Ctrl+Q+Q

    def on_trigger() -> None:
        import time as _time
        now = _time.time()
        last = state.get("last_q_time", 0.0)
        state["last_q_time"] = now

        is_double = (now - last) < DOUBLE_Q_THRESHOLD

        try:
            simulate_ctrl_c(copy_delay)

            if is_double:
                # Ctrl+Q+Q：触发一次生成流程（_process_clipboard 内部已自动粘贴）
                _process_clipboard(bot, default_chat, copy_reply, min_len, state, force=True)
                print("[INFO] Ctrl+Q+Q handled")
            else:
                # 普通 Ctrl+Q：只生成
                _process_clipboard(bot, default_chat, copy_reply, min_len, state, force=True)

        except Exception as e:
            print(f"[ERROR] 处理失败: {e}")
            toast_error("处理失败", bot.cfg)

    def on_reanswer() -> None:
        try:
            simulate_ctrl_c(copy_delay)
            _process_clipboard(
                bot, default_chat, copy_reply, min_len, state, force=True, force_ai=True
            )
            print("[INFO] Ctrl+R handled")
        except Exception as e:
            print(f"[ERROR] Ctrl+R 处理失败: {e}")
            toast_error("Ctrl+R 处理失败", bot.cfg)

    def on_exit() -> None:
        print("\n[INFO] 已退出")

    try:
        run_hotkey_loop(on_trigger, on_exit, on_reanswer=on_reanswer)
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        print("[INFO] Fallback to clipboard polling (manual Ctrl+C then auto-process)")
        _run_clipboard_poll_fallback(
            bot, default_chat, copy_reply, min_len, cb_cfg, state
        )


def _run_clipboard_poll_fallback(
    bot: MessageBot,
    default_chat: str,
    copy_reply: bool,
    min_len: int,
    cb_cfg: dict,
    state: dict,
) -> None:
    interval = float(cb_cfg.get("poll_interval_sec", 0.6))
    print("[INFO] Ctrl+Shift+Q or close window to exit")
    print("[INFO] Polling mode: 不会自动处理剪贴板，请手动 Ctrl+C 复制问题后按 Ctrl+Q 生成回复")
    while True:
        try:
            text = (get_text() or "").strip()
            # polling 模式下只检测变化，不自动调用 _process_clipboard
            # 避免“还没按 Ctrl+Q 就自动回答”的问题
            if text and text != state.get("last_seen") and len(text) >= min_len:
                print("[INFO] 检测到剪贴板变化，请按 Ctrl+Q 生成回复（或 Ctrl+Q+Q 自动粘贴）")
            state["last_seen"] = text
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[INFO] 已退出")
            break
