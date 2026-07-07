"""非侵入式右下角 Toast：不抢焦点，显示数秒后自动淡出。"""
from __future__ import annotations

import queue
import threading
from typing import Literal

ToastKind = Literal["info", "success", "warn", "error"]

_manager: "ToastManager | None" = None
_manager_lock = threading.Lock()


class ToastManager:
    def __init__(
        self,
        *,
        duration_sec: float = 3.0,
        fade_ms: int = 450,
        max_width: int = 360,
    ):
        self.duration_sec = max(0.5, float(duration_sec))
        self.fade_ms = max(100, int(fade_ms))
        self.max_width = max_width
        self._queue: queue.Queue[tuple[str, ToastKind, float | None]] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="toast-ui", daemon=True)
        self._thread.start()

    def show(self, message: str, kind: ToastKind = "info", duration_sec: float | None = None) -> None:
        text = (message or "").strip()
        if not text:
            return
        self._queue.put((text, kind, duration_sec))

    def _run(self) -> None:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        active: list[tk.Toplevel] = []

        def poll() -> None:
            try:
                while True:
                    msg, kind, dur = self._queue.get_nowait()
                    self._spawn(root, msg, kind, dur, active)
            except queue.Empty:
                pass
            root.after(80, poll)

        root.after(80, poll)
        root.mainloop()

    def _spawn(
        self,
        root: "object",
        message: str,
        kind: ToastKind,
        duration_sec: float | None,
        active: list,
    ) -> None:
        import tkinter as tk

        # 同时只保留最新一条，避免堆叠遮挡
        for win in active[:]:
            try:
                win.destroy()
            except Exception:
                pass
        active.clear()

        hold = self.duration_sec if duration_sec is None else max(0.5, float(duration_sec))
        colors = {
            "info": ("#1e3a5f", "#58a6ff", "#0d1117"),
            "success": ("#1a3d2e", "#3fb950", "#0d1117"),
            "warn": ("#4d3d1a", "#d29922", "#0d1117"),
            "error": ("#4d1f1f", "#f85149", "#0d1117"),
        }
        accent_bg, accent_fg, panel_bg = colors.get(kind, colors["info"])

        win = tk.Toplevel(root)
        active.append(win)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.0)

        frame = tk.Frame(win, bg=panel_bg, highlightthickness=1, highlightbackground="#30363d")
        frame.pack(fill="both", expand=True)
        bar = tk.Frame(frame, bg=accent_fg, width=4)
        bar.pack(side="left", fill="y")
        inner = tk.Frame(frame, bg=panel_bg, padx=14, pady=10)
        inner.pack(side="left", fill="both", expand=True)

        title_map = {
            "info": "WeChat Bot",
            "success": "完成",
            "warn": "提示",
            "error": "失败",
        }
        tk.Label(
            inner,
            text=title_map.get(kind, "WeChat Bot"),
            fg=accent_fg,
            bg=panel_bg,
            font=("Microsoft YaHei UI", 9, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            inner,
            text=message,
            fg="#e6edf3",
            bg=panel_bg,
            font=("Microsoft YaHei UI", 10),
            anchor="w",
            justify="left",
            wraplength=self.max_width,
        ).pack(fill="x", pady=(4, 0))

        win.update_idletasks()
        w = min(self.max_width + 40, max(win.winfo_reqwidth(), 220))
        h = win.winfo_reqheight()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = sw - w - 24
        y = sh - h - 72
        win.geometry(f"{w}x{h}+{x}+{y}")

        self._no_activate(win)
        self._fade_in_then_out(win, hold)

    def _no_activate(self, win) -> None:
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
            if not hwnd:
                hwnd = win.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x00000080
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
            )
        except Exception:
            pass

    def _fade_in_then_out(self, win, hold_sec: float) -> None:
        target = 0.94
        steps_in = 8
        step_in = target / steps_in

        def fade_in(alpha: float = 0.0) -> None:
            if alpha >= target:
                win.after(int(hold_sec * 1000), lambda: fade_out(target))
                return
            alpha = min(target, alpha + step_in)
            try:
                win.attributes("-alpha", alpha)
                win.after(25, lambda: fade_in(alpha))
            except Exception:
                pass

        def fade_out(alpha: float) -> None:
            steps = max(5, self.fade_ms // 30)
            step = alpha / steps
            if alpha <= 0:
                try:
                    win.destroy()
                except Exception:
                    pass
                return
            alpha = max(0.0, alpha - step)
            try:
                win.attributes("-alpha", alpha)
                win.after(30, lambda: fade_out(alpha))
            except Exception:
                try:
                    win.destroy()
                except Exception:
                    pass

        fade_in(0.0)


def init_toast(cfg: dict | None = None) -> ToastManager | None:
    global _manager
    cb = (cfg or {}).get("clipboard") or {}
    if cb.get("toast_enabled") is False:
        return None
    dur = float(cb.get("toast_duration_sec", 3))
    fade = int(cb.get("toast_fade_ms", 450))
    with _manager_lock:
        if _manager is None:
            _manager = ToastManager(duration_sec=dur, fade_ms=fade)
        return _manager


def toast_show(
    message: str,
    kind: ToastKind = "info",
    cfg: dict | None = None,
    duration_sec: float | None = None,
) -> None:
    global _manager
    mgr = _manager or init_toast(cfg)
    if mgr is None:
        return
    mgr.show(message, kind=kind, duration_sec=duration_sec)


def toast_generating(cfg: dict | None = None) -> None:
    toast_show("正在生成答案…", kind="info", cfg=cfg)


def toast_done(cfg: dict | None = None, *, preview: str = "") -> None:
    msg = "答案已生成"
    if preview:
        one_line = preview.replace("\n", " ").strip()
        if len(one_line) > 36:
            one_line = one_line[:36] + "…"
        msg = f"答案已生成：{one_line}"
    toast_show(msg, kind="success", cfg=cfg)


def toast_file_ready(cfg: dict | None = None) -> None:
    toast_show("文件已复制，在微信 Ctrl+V 发送", kind="success", cfg=cfg)


def toast_warn(message: str, cfg: dict | None = None) -> None:
    toast_show(message, kind="warn", cfg=cfg)


def toast_error(message: str, cfg: dict | None = None) -> None:
    toast_show(message, kind="error", cfg=cfg)
