"""Windows 全局热键（默认 Ctrl+Q 触发，Ctrl+Shift+Q 退出）。"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32

WM_HOTKEY = 0x0312
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
VK_Q = 0x51
VK_W = 0x57
VK_R = 0x52
VK_C = 0x43
VK_CONTROL = 0x11

HOTKEY_TRIGGER = 1
HOTKEY_EXIT = 2
HOTKEY_PASTE_ANSWER = 3
HOTKEY_REANSWER = 4

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

PUL = ctypes.POINTER(ctypes.c_ulong)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL),
    ]


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    _anonymous_ = ("_input",)
    _fields_ = [("type", wintypes.DWORD), ("_input", _INPUT)]


def simulate_ctrl_c(delay_sec: float = 0.12) -> None:
    """向当前前台窗口发送 Ctrl+C（复制选中内容到剪贴板）。"""
    extra = ctypes.c_ulong(0)

    def press(vk: int, flags: int = 0) -> None:
        inp = INPUT(
            type=INPUT_KEYBOARD,
            ki=KEYBDINPUT(wVk=vk, dwFlags=flags, dwExtraInfo=ctypes.pointer(extra)),
        )
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    press(VK_CONTROL)
    press(VK_C)
    press(VK_C, KEYEVENTF_KEYUP)
    press(VK_CONTROL, KEYEVENTF_KEYUP)
    if delay_sec > 0:
        time.sleep(delay_sec)


def press_key(vk: int, flags: int = 0) -> None:
    """发送单个按键（用于模拟 Ctrl+V 等）。"""
    extra = ctypes.c_ulong(0)
    inp = INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(wVk=vk, dwFlags=flags, dwExtraInfo=ctypes.pointer(extra)),
    )
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def run_hotkey_loop(on_trigger, on_exit, on_paste_answer=None, on_reanswer=None) -> None:
    """阻塞运行消息循环。
    Ctrl+Q 触发生成，Ctrl+R 强制 AI 重新回答，Ctrl+W 粘贴上次答案，Ctrl+Shift+Q 退出。
    """
    if not user32.RegisterHotKey(None, HOTKEY_TRIGGER, MOD_CONTROL, VK_Q):
        raise RuntimeError("注册 Ctrl+Q 失败，可能被其他程序占用")
    if not user32.RegisterHotKey(None, HOTKEY_EXIT, MOD_CONTROL | MOD_SHIFT, VK_Q):
        user32.UnregisterHotKey(None, HOTKEY_TRIGGER)
        raise RuntimeError("注册 Ctrl+Shift+Q 失败")
    # Ctrl+W / Ctrl+R 注册失败不致命（浏览器等可能占用），静默跳过
    user32.RegisterHotKey(None, HOTKEY_PASTE_ANSWER, MOD_CONTROL, VK_W)
    user32.RegisterHotKey(None, HOTKEY_REANSWER, MOD_CONTROL, VK_R)

    msg = wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                if msg.wParam == HOTKEY_TRIGGER:
                    on_trigger()
                elif msg.wParam == HOTKEY_EXIT:
                    on_exit()
                    break
                elif msg.wParam == HOTKEY_PASTE_ANSWER and on_paste_answer:
                    on_paste_answer()
                elif msg.wParam == HOTKEY_REANSWER and on_reanswer:
                    on_reanswer()
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        user32.UnregisterHotKey(None, HOTKEY_TRIGGER)
        user32.UnregisterHotKey(None, HOTKEY_EXIT)
        for hid in (HOTKEY_PASTE_ANSWER, HOTKEY_REANSWER):
            try:
                user32.UnregisterHotKey(None, hid)
            except Exception:
                pass
