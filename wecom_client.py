"""企业微信 API：access_token、发消息、发文件。"""
from __future__ import annotations

import os
import time
from typing import Optional

import requests


class WeComClient:
    def __init__(self, cfg: dict):
        self.corpid = str(cfg.get("corpid", ""))
        self.corpsecret = str(cfg.get("corpsecret", ""))
        self.agentid = int(cfg.get("agentid", 0))
        self._token = ""
        self._token_expire_at = 0.0

    def _ensure_config(self):
        if not self.corpid or not self.corpsecret or not self.agentid:
            raise RuntimeError("wecom.corpid / corpsecret / agentid 未配置")

    def get_access_token(self, force: bool = False) -> str:
        self._ensure_config()
        now = time.time()
        if not force and self._token and now < self._token_expire_at - 60:
            return self._token
        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        resp = requests.get(
            url,
            params={"corpid": self.corpid, "corpsecret": self.corpsecret},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode", -1) != 0:
            raise RuntimeError(f"gettoken failed: {data}")
        self._token = data["access_token"]
        self._token_expire_at = now + int(data.get("expires_in", 7200))
        return self._token

    def send_text(self, userid: str, content: str) -> bool:
        token = self.get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
        payload = {
            "touser": userid,
            "msgtype": "text",
            "agentid": self.agentid,
            "text": {"content": content},
            "safe": 0,
        }
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode", -1) != 0:
            print(f"[ERROR] wecom send_text: {data}")
            return False
        return True

    def upload_media(self, file_path: str, media_type: str = "file") -> Optional[str]:
        if not os.path.isfile(file_path):
            print(f"[ERROR] file not found: {file_path}")
            return None
        token = self.get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/media/upload?access_token={token}&type={media_type}"
        with open(file_path, "rb") as f:
            resp = requests.post(url, files={"media": (os.path.basename(file_path), f)}, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode", -1) != 0:
            print(f"[ERROR] wecom upload_media: {data}")
            return None
        return data.get("media_id")

    def send_file(self, userid: str, file_path: str) -> bool:
        media_id = self.upload_media(file_path, "file")
        if not media_id:
            return False
        token = self.get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
        payload = {
            "touser": userid,
            "msgtype": "file",
            "agentid": self.agentid,
            "file": {"media_id": media_id},
            "safe": 0,
        }
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode", -1) != 0:
            print(f"[ERROR] wecom send_file: {data}")
            return False
        return True
