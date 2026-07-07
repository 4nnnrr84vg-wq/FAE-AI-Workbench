"""本机手动模式：不连企业微信 API，复制消息进来，草稿复制出去。"""
from __future__ import annotations

from text_encoding import FILE_ENCODING, open_text, read_text, write_text

from env_loader import load_local_env

load_local_env()

from bot_core import MessageBot


def _check_ai_ready(cfg: dict) -> None:
    from model_client import ModelClient

    m = ModelClient(cfg)
    if m.enabled and m.api_key:
        print(f"[OK] model_api 已加载（模型 {m.model}，base_url={m.base_url}）")
        return

    if m.enabled and not m.api_key:
        print(
            "[ERROR] model_api.enabled=true，但未检测到 DEEPSEEK_API_KEY！\n"
            "  请双击 set_api_key.bat 填入 DeepSeek/OpenAI-compatible API Key，\n"
            "  然后重新运行 main.py"
        )
        return

    print("[WARN] model_api.enabled=false，不会调用 AI，只能使用关键词/本地检索")


def _base_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _inbox_path(cfg: dict) -> str:
    name = str(cfg.get("bot", {}).get("local_inbox_txt", "message_inbox.txt"))
    return os.path.join(_base_dir(), name)


def _state_path(cfg: dict) -> str:
    return _inbox_path(cfg) + ".offset"


def _read_offset(cfg: dict) -> int:
    path = _state_path(cfg)
    if not os.path.exists(path):
        return 0
    try:
        with open_text(path) as f:
            return int(f.read().strip() or "0")
    except ValueError:
        return 0


def _write_offset(cfg: dict, offset: int) -> None:
    with open_text(_state_path(cfg), "w") as f:
        f.write(str(offset))


def _parse_line(line: str) -> tuple[str, str]:
    """支持 [会话名] 消息内容 或纯文本。"""
    line = line.strip()
    if not line or line.startswith("#"):
        return "", ""
    if line.startswith("[") and "]" in line:
        end = line.index("]")
        chat = line[1:end].strip() or "所有会话"
        text = line[end + 1 :].strip()
        return chat, text
    return "所有会话", line


def process_text(bot: MessageBot, chat: str, text: str) -> None:
    if not text:
        return
    bot.handle_message(
        {
            "chat": chat,
            "sender": "manual",
            "content": text,
            "type": "text",
        }
    )


def run_interactive(cfg: dict) -> None:
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    bot = MessageBot(cfg, sender=None)
    draft = bot.draft_file
    print("[INFO] 本机交互模式（local）")
    print(f"[INFO] 草稿输出: {draft}")
    print("[INFO] 输入对方消息，回车生成草稿；空行退出")
    print("[INFO] 可选格式: [群名或联系人] 消息内容")
    print("-" * 50)
    default_chat = str(cfg.get("bot", {}).get("local_default_chat", "所有会话"))
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[INFO] 已退出")
            break
        if not line:
            break
        if line.startswith("["):
            chat, text = _parse_line(line)
        else:
            chat, text = default_chat, line
        process_text(bot, chat, text)
        print(f"[INFO] 请打开 {draft} 复制 TEXT 行到聊天框\n")


def _ensure_inbox(cfg: dict) -> str:
    path = _inbox_path(cfg)
    if not os.path.exists(path):
        with open_text(path, "w") as f:
            f.write(
                "# 将企业微信/微信里收到的消息粘贴到本文件下方，保存即可生成草稿\n"
                "# 每行一条；或以 [会话名] 开头，例如:\n"
                "# [OTA群] 升级失败怎么办\n\n"
            )
    return path


def run_inbox_watch(cfg: dict) -> None:
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    bot = MessageBot(cfg, sender=None)
    inbox = _ensure_inbox(cfg)
    draft = bot.draft_file
    interval = float(cfg.get("bot", {}).get("local_poll_interval_sec", 1.0))
    offset = _read_offset(cfg)

    print("[INFO] 本机收件箱模式（local + inbox）")
    print(f"[INFO] 编辑并保存: {inbox}")
    print(f"[INFO] 草稿输出: {draft}")
    print("[INFO] Ctrl+C 退出")
    print("-" * 50)

    while True:
        try:
            if os.path.exists(inbox):
                size = os.path.getsize(inbox)
                if size > offset:
                    with open_text(inbox) as f:
                        f.seek(offset)
                        chunk = f.read()
                    _write_offset(cfg, size)
                    for line in chunk.splitlines():
                        chat, text = _parse_line(line)
                        if text:
                            process_text(bot, chat, text)
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[INFO] 已退出")
            break


def run_local(cfg: dict) -> None:
    sub = str(cfg.get("bot", {}).get("local_mode", "inbox")).lower()
    if sub == "clipboard":
        from clipboard_mode import run_clipboard_watch

        run_clipboard_watch(cfg)
        return
    _check_ai_ready(cfg)
    if sub in ("repl", "interactive", "cli"):
        run_interactive(cfg)
    else:
        run_inbox_watch(cfg)
