"""PC 微信自动化客户端（wxauto4 / wxautox4），支持轮询与回调两种监听。"""
from __future__ import annotations

import sys
import threading
import time
from typing import Callable


class WeChatPcClient:
  """监听 PC 微信消息并发送回复。需 Windows 微信客户端 + wxauto4 授权。"""

  def __init__(
      self,
      allowed_chats: list[str],
      *,
      retry_interval_sec: int = 5,
      wechat_ads: bool = False,
      ignore_self: bool = True,
      listen_mode: str = "callback",
      my_nicknames: list[str] | None = None,
  ):
      self.allowed_chats = [c for c in allowed_chats if c]
      self.retry_interval_sec = max(1, retry_interval_sec)
      self.wechat_ads = wechat_ads
      self.ignore_self = ignore_self
      self.listen_mode = listen_mode.lower()
      self.my_nicknames = set(my_nicknames or [])
      self.available = False
      self.wx = None
      self._last_init_try_ts = 0.0
      self._handler: Callable[[dict], None] | None = None
      self._init_client()

  def _init_client(self) -> None:
      self._last_init_try_ts = time.time()
      self.available = False
      self.wx = None
      last_err = ""

      if sys.version_info >= (3, 9):
          for pkg, cls_name in (("wxauto4", "WeChat"), ("wxautox4", "WeChat")):
              try:
                  mod = __import__(pkg, fromlist=[cls_name])
                  WeChatCls = getattr(mod, cls_name)
                  self.wx = WeChatCls(ads=self.wechat_ads)
                  self.available = True
                  print(f"[INFO] {pkg} 已连接，监听: {self.allowed_chats}")
                  return
              except Exception as e:
                  last_err = f"{pkg}: {e}"

      try:
          from wxauto import WeChat as WeChat39

          self.wx = WeChat39()
          self.available = True
          print(f"[INFO] wxauto 3.9 已连接，监听: {self.allowed_chats}")
      except Exception as e:
          if last_err:
              print(f"[WARN] {last_err}")
          print(f"[WARN] 微信自动化初始化失败: {e}")
          print("[HINT] pip install wxauto4 ；微信 4.1.x 可能需要 wxautox Plus 授权")

  def _ensure_ready(self) -> None:
      if self.available:
          return
      if time.time() - self._last_init_try_ts >= self.retry_interval_sec:
          self._init_client()

  def _chat_name(self, chat_obj) -> str:
      return str(getattr(chat_obj, "who", None) or chat_obj)

  def _should_skip(self, msg) -> bool:
      msg_type = str(getattr(msg, "type", "") or "").lower()
      if msg_type in ("self", "time", "sys", "system", "recall"):
          return True
      if msg_type and msg_type not in ("friend", "text", "group", "other"):
          # 未知类型：有文字内容则尝试处理
          if not str(getattr(msg, "content", "") or "").strip():
              return True
      content = str(getattr(msg, "content", "") or "").strip()
      if not content:
          return True
      sender = str(getattr(msg, "sender", "") or "").strip()
      if self.ignore_self and sender:
          if sender in self.my_nicknames:
              return True
          if sender == "我":
              return True
      return False

  def _msg_to_dict(self, msg, chat_name: str) -> dict:
      return {
          "chat": chat_name,
          "sender": str(getattr(msg, "sender", "") or ""),
          "content": str(getattr(msg, "content", "") or "").strip(),
          "type": str(getattr(msg, "type", "text") or "text"),
      }

  def _on_raw_message(self, msg, chat_obj) -> None:
      if not self._handler or self._should_skip(msg):
          return
      chat_name = self._chat_name(chat_obj)
      if self.allowed_chats and chat_name not in self.allowed_chats:
          return
      try:
          self._handler(self._msg_to_dict(msg, chat_name))
      except Exception as e:
          print(f"[ERROR] 处理消息失败: {e}")

  def _register_listen_callback(self) -> None:
      if not self.wx or not self.allowed_chats:
          return

      def callback(msg, chat):
          self._on_raw_message(msg, chat)

      for chat in self.allowed_chats:
          try:
              self.wx.AddListenChat(who=chat, callback=callback)
          except TypeError:
              try:
                  self.wx.AddListenChat(chat, callback)
              except TypeError:
                  self.wx.AddListenChat(chat)

  def _register_listen_poll(self) -> None:
      if not self.wx:
          return
      for chat in self.allowed_chats:
          try:
              self.wx.AddListenChat(who=chat, savepic=False)
          except TypeError:
              self.wx.AddListenChat(chat)

  def run(self, on_message: Callable[[dict], None]) -> None:
      """阻塞运行。listen_mode=callback 用事件回调，poll 用轮询。"""
      self._handler = on_message
      self._ensure_ready()
      if not self.available:
          print("[ERROR] 微信未就绪，请确认 PC 微信已登录且 wxauto4 已安装/授权")
          return

      if self.listen_mode == "callback":
          self._run_callback()
      else:
          self._run_poll()

  def _run_callback(self) -> None:
      self._register_listen_callback()
      print("[INFO] 回调监听已启动（与 B 站教程 AddListenChat 方式一致）")
      print("[INFO] 请保持微信窗口不要最小化到托盘；Ctrl+C 退出")

      if hasattr(self.wx, "KeepRunning"):
          try:
              self.wx.KeepRunning()
              return
          except Exception as e:
              print(f"[WARN] KeepRunning 不可用: {e}，改用轮询")

      if hasattr(self.wx, "_listener_start"):
          try:
              self.wx._listener_start()
          except Exception:
              pass

      try:
          while True:
              time.sleep(1)
      except KeyboardInterrupt:
          print("\n[INFO] 已停止")

  def _run_poll(self, interval: float = 2.0) -> None:
      self._register_listen_poll()
      print(f"[INFO] 轮询监听已启动，间隔 {interval}s")
      while True:
          try:
              for msg in self.fetch_messages():
                  if self._handler:
                      self._handler(msg)
          except KeyboardInterrupt:
              print("\n[INFO] 已停止")
              break
          except Exception as e:
              print(f"[ERROR] 轮询异常: {e}")
          time.sleep(interval)

  def fetch_messages(self) -> list[dict]:
      self._ensure_ready()
      if not self.available:
          return []
      result: list[dict] = []
      try:
          msg_map = self.wx.GetListenMessage()
          for chat_obj, items in msg_map.items():
              chat_name = self._chat_name(chat_obj)
              for m in items:
                  if self._should_skip(m):
                      continue
                  result.append(self._msg_to_dict(m, chat_name))
      except Exception as e:
          print(f"[ERROR] 拉取消息失败: {e}")
          self.available = False
          self.wx = None
      return result

  def send_text(self, chat: str, text: str) -> bool:
      self._ensure_ready()
      if not self.available or not text:
          return False
      try:
          try:
              self.wx.SendMsg(msg=text, who=chat)
          except TypeError:
              self.wx.SendMsg(text, chat)
          print(f"[SEND] {chat}: {text[:80]}{'...' if len(text) > 80 else ''}")
          return True
      except Exception as e:
          print(f"[ERROR] 发送失败: {e}")
          return False

  def send_file(self, chat: str, path: str) -> bool:
      self._ensure_ready()
      if not self.available:
          return False
      try:
          try:
              self.wx.SendFiles(filepath=path, who=chat)
          except TypeError:
              self.wx.SendFiles(path, chat)
          return True
      except Exception as e:
          print(f"[ERROR] 发送文件失败: {e}")
          return False
