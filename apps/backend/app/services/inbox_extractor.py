from __future__ import annotations

import re

from app.schemas import CustomerIssue, InboxParseRequest
from app.services.text_utils import (
    FW_RE,
    SDK_RE,
    VERSION_RE,
    extract_error_keywords,
    normalize_space,
    unique_keep_order,
)


OWNER_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("WiFi SDK", ("wifi", "wlan", "联网", "ssid", "dhcp", "ap", "sta")),
    ("BLE SDK", ("ble", "蓝牙", "gatt", "gap", "pair", "bond", "广播", "连接")),
    ("Power/LowPower", ("sleep", "deepsleep", "lightsleep", "低功耗", "唤醒", "pwr", "rtc")),
    ("Boot/OTA", ("boot", "ota", "升级", "固件", "crc", "flash")),
    ("Driver", ("gpio", "uart", "spi", "i2c", "adc", "pwm", "timer")),
    ("Hardware", ("硬件", "原理图", "板子", "rev", "电源", "晶振")),
]


class InboxExtractor:
    def parse(self, req: InboxParseRequest) -> CustomerIssue:
        raw = "\n".join(part for part in [req.chat_context, req.text] if part).strip()
        text = normalize_space(raw)
        sdk_version = self._first_group(SDK_RE, text) or self._near_version(text, ("sdk", "SDK"))
        firmware_version = self._first_group(FW_RE, text) or self._near_version(
            text, ("fw", "固件", "firmware")
        )
        issue = CustomerIssue(
            customer=self._customer(req.customer_hint, text),
            product_model=self._product_model(text),
            sdk_version=sdk_version,
            firmware_version=firmware_version,
            hardware_model=self._hardware_model(text),
            symptom=self._symptom(text),
            error_keywords=extract_error_keywords(text),
            attachments=unique_keep_order(req.attachments + self._attachment_names(text)),
            missing_info=[],
            priority=self._priority(text),
            suggested_owner=self._owner(text),
            raw_text=raw,
            confidence=self._confidence(text),
        )
        issue.missing_info = self._missing_info(issue, text)
        return issue

    def _first_group(self, pattern: re.Pattern[str], text: str) -> str:
        match = pattern.search(text)
        return match.group(1).strip() if match else ""

    def _near_version(self, text: str, labels: tuple[str, ...]) -> str:
        for label in labels:
            pattern = re.compile(rf"{re.escape(label)}[^0-9vV]{{0,12}}({VERSION_RE.pattern})", re.I)
            match = pattern.search(text)
            if match:
                return match.group(1)
        return ""

    def _customer(self, hint: str, text: str) -> str:
        if hint.strip():
            return hint.strip()
        match = re.search(r"(?:客户|customer|公司)\s*[:=： ]\s*([\u4e00-\u9fffA-Za-z0-9_-]{2,30})", text, re.I)
        return match.group(1) if match else "未识别客户"

    def _product_model(self, text: str) -> str:
        patterns = [
            r"(?:型号|产品型号|硬件型号|product|model)\s*[:=： ]\s*([A-Za-z0-9_-]+(?:\s+Rev\.?[A-Za-z0-9]+)?)",
            r"\b(XC\d{4,5}[A-Za-z0-9_-]*)\b",
            r"\b([A-Z]{1,4}\d{2,5}(?:[-_][A-Za-z0-9]+)?(?:\s+Rev\.?[A-Za-z0-9]+)?)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return match.group(1).strip()
        return ""

    def _hardware_model(self, text: str) -> str:
        match = re.search(r"(?:硬件|板子|PCB|HW)\s*[:=： ]\s*([A-Za-z0-9_. -]{2,40})", text, re.I)
        return match.group(1).strip() if match else ""

    def _symptom(self, text: str) -> str:
        labeled = re.search(r"(?:现象|症状|问题|表现)\s*[:=： ]\s*(.{4,160})", text, re.I)
        if labeled:
            return normalize_space(labeled.group(1))[:180]
        symptom = re.search(
            r"((?:升级|浅睡|深睡|连接|联网|wifi|ble|gpio|uart|ota|配对|广播).{0,80}"
            r"(?:失败|无法|异常|不通|死机|复位|断连|连不上|唤醒不了|不联网|超时).{0,50})",
            text,
            re.I,
        )
        if symptom:
            return self._clean_symptom(symptom.group(1))
        generic = re.search(r"(.{0,30}(?:失败|无法|异常|不通|死机|复位|断连|连不上|唤醒不了|不联网).{0,60})", text, re.I)
        if generic:
            return self._clean_symptom(generic.group(1))
        return text[:180]

    def _clean_symptom(self, text: str) -> str:
        text = re.split(r"(?:，?已?附|附件|截图|boot\.log)", text, maxsplit=1, flags=re.I)[0]
        return normalize_space(text.strip(" ，,。."))[:180]

    def _attachment_names(self, text: str) -> list[str]:
        return re.findall(r"[\w\u4e00-\u9fff.-]+\.(?:log|txt|png|jpg|jpeg|zip|7z|rar|bin|pcapng)", text, re.I)

    def _missing_info(self, issue: CustomerIssue, text: str) -> list[str]:
        missing: list[str] = []
        if not issue.product_model:
            missing.append("芯片/产品型号")
        if not issue.sdk_version:
            missing.append("SDK 版本")
        if not issue.firmware_version:
            missing.append("当前固件版本")
        if "升级" in text and "升级前" not in text:
            missing.append("升级前版本")
        if not issue.attachments and not issue.error_keywords:
            missing.append("完整 boot log 或错误截图")
        if any(k in text.lower() for k in ("wifi", "联网", "wlan")) and "ssid" not in text.lower():
            missing.append("WiFi 配置和初始化参数")
        return unique_keep_order(missing)

    def _priority(self, text: str) -> str:
        low = text.lower()
        if any(k in low for k in ("量产停线", "批量", "无法开机", "brick", "安全事故")):
            return "P0"
        if any(k in low for k in ("死机", "hardfault", "panic", "复位", "无法联网", "升级失败")):
            return "P1"
        if any(k in low for k in ("异常", "失败", "无法", "error", "failed")):
            return "P2"
        return "P3"

    def _owner(self, text: str) -> str:
        low = text.lower()
        for owner, keys in OWNER_RULES:
            if any(key.lower() in low for key in keys):
                return owner
        return "FAE"

    def _confidence(self, text: str) -> float:
        signals = 0
        for pattern in (SDK_RE, FW_RE, VERSION_RE):
            signals += 1 if pattern.search(text) else 0
        if extract_error_keywords(text):
            signals += 1
        if self._product_model(text):
            signals += 1
        return min(0.95, 0.35 + signals * 0.12)
