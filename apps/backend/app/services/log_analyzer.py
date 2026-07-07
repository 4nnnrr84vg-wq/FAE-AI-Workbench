from __future__ import annotations

import re

from app.schemas import LogAnalysis, LogAnalyzeRequest, LogContext
from app.services.knowledge_base import KnowledgeBase
from app.services.text_utils import extract_error_keywords, unique_keep_order


TIMESTAMP_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[,.]\d+)?)|"
    r"(\[\s*\d+(?:\.\d+)?\s*\])|"
    r"(\b\d{2}:\d{2}:\d{2}(?:[,.]\d+)?\b)"
)
ERROR_LINE_RE = re.compile(
    r"error|failed|fail|assert|panic|fault|exception|timeout|crc|invalid|"
    r"异常|失败|超时|复位|死机|错误|断连|无法",
    re.I,
)

MODULE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("WiFi SDK", ("wifi", "wlan", "dhcp", "ssid", "WIFI_")),
    ("BLE SDK", ("ble", "gap", "gatt", "att", "smp", "bond", "pair", "蓝牙")),
    ("Boot/OTA", ("boot", "ota", "crc", "image", "upgrade", "flash", "升级")),
    ("Power/LowPower", ("sleep", "wake", "rtc", "pwr", "deepsleep", "lightsleep", "唤醒", "低功耗")),
    ("Driver/UART", ("uart", "rxd", "txd", "serial")),
    ("Driver/GPIO", ("gpio", "pin", "io wake")),
    ("Storage/NVDS", ("nvds", "nvm", "config", "storage", "flash")),
]


class LogAnalyzer:
    def __init__(self, kb: KnowledgeBase):
        self.kb = kb

    def analyze(self, req: LogAnalyzeRequest) -> LogAnalysis:
        lines = req.log_text.splitlines()
        key_indexes = [idx for idx, line in enumerate(lines) if ERROR_LINE_RE.search(line)]
        key_error_lines = [f"{idx + 1}: {lines[idx].strip()[:240]}" for idx in key_indexes[:20]]
        error_codes = extract_error_keywords(req.log_text, 20)
        module_owner = self._module_owner(req.log_text)
        timeline = self._timeline(lines)
        contexts = self._contexts(lines, key_indexes[:8])
        hypotheses = self._hypotheses(req, module_owner, error_codes)
        missing_info = self._missing_info(req, key_error_lines)
        checklist = self._checklist(module_owner)

        search_query = " ".join(
            part
            for part in [
                req.product_model,
                req.sdk_version,
                req.firmware_version,
                module_owner,
                " ".join(error_codes[:5]),
                " ".join(key_error_lines[:3]),
            ]
            if part
        )
        related_docs = self.kb.search(search_query or req.log_text[:200], req.top_k_sources)

        return LogAnalysis(
            key_error_lines=key_error_lines,
            error_codes=error_codes,
            module_owner=module_owner,
            timeline=timeline,
            contexts=contexts,
            hypotheses=hypotheses,
            missing_info=missing_info,
            related_docs=related_docs,
            checklist=checklist,
        )

    def _module_owner(self, text: str) -> str:
        low = text.lower()
        scores: list[tuple[int, str]] = []
        for owner, keys in MODULE_RULES:
            score = sum(low.count(key.lower()) for key in keys)
            if score:
                scores.append((score, owner))
        if not scores:
            return "Unknown"
        return sorted(scores, reverse=True)[0][1]

    def _timeline(self, lines: list[str]) -> list[str]:
        out: list[str] = []
        for idx, line in enumerate(lines):
            if TIMESTAMP_RE.search(line) or ERROR_LINE_RE.search(line):
                out.append(f"{idx + 1}: {line.strip()[:220]}")
            if len(out) >= 30:
                break
        return out

    def _contexts(self, lines: list[str], indexes: list[int]) -> list[LogContext]:
        contexts: list[LogContext] = []
        for idx in indexes:
            start = max(0, idx - 2)
            end = min(len(lines), idx + 3)
            contexts.append(
                LogContext(
                    line=idx + 1,
                    before=[f"{i + 1}: {lines[i]}" for i in range(start, idx)],
                    current=f"{idx + 1}: {lines[idx]}",
                    after=[f"{i + 1}: {lines[i]}" for i in range(idx + 1, end)],
                )
            )
        return contexts

    def _hypotheses(self, req: LogAnalyzeRequest, owner: str, codes: list[str]) -> list[str]:
        base: list[str] = []
        low = req.log_text.lower()
        if owner == "WiFi SDK":
            base.append("WiFi 初始化、配置迁移或连接参数不一致，优先核对初始化顺序、SSID/加密方式和 DHCP 阶段日志。")
        if owner == "BLE SDK":
            base.append("BLE 状态机、绑定信息或连接参数异常，优先核对 GAP/GATT 流程和历史绑定数据。")
        if owner == "Boot/OTA":
            base.append("升级包、Flash 布局或 CRC 校验异常，优先核对 OTA 文件、分区地址和升级前后版本。")
        if owner == "Power/LowPower":
            base.append("低功耗唤醒源或时钟配置异常，优先核对 sleep 前后 GPIO/RTC/UART 配置。")
        if "timeout" in low or "超时" in low:
            base.append("存在超时信号，需要确认外设响应时间、任务调度阻塞和网络/射频环境。")
        if any("0x" in code.lower() for code in codes):
            base.append("日志包含十六进制错误码，需要按对应模块错误码表反查含义。")
        if not base:
            base.append("日志中的错误信号不足，只能作为初步线索，需要补充完整 boot log 和复现步骤。")
        return unique_keep_order(base)[:6]

    def _missing_info(self, req: LogAnalyzeRequest, key_lines: list[str]) -> list[str]:
        missing: list[str] = []
        if not req.sdk_version:
            missing.append("SDK 版本")
        if not req.firmware_version:
            missing.append("固件版本和升级前版本")
        if len(req.log_text.splitlines()) < 20:
            missing.append("完整 boot log")
        if not key_lines:
            missing.append("异常发生前后 30 秒日志")
        missing.append("复现步骤和发生概率")
        return unique_keep_order(missing)

    def _checklist(self, owner: str) -> list[str]:
        common = [
            "确认客户硬件型号、SDK 版本、固件版本和升级前版本。",
            "要求客户提供完整 boot log，不只截取错误行。",
            "记录复现步骤、发生概率和是否清除旧配置。",
        ]
        module_map = {
            "WiFi SDK": [
                "核对 WiFi 初始化调用顺序和配置迁移逻辑。",
                "确认 AP 加密方式、SSID、密码、DHCP 阶段日志。",
            ],
            "BLE SDK": [
                "核对广播、连接、配对绑定、GATT 读写流程。",
                "确认是否存在旧绑定信息或连接参数不兼容。",
            ],
            "Boot/OTA": [
                "核对 OTA 包命名、CRC、Flash 分区和 boot 参数。",
                "对比升级前后 release notes 中的兼容性说明。",
            ],
            "Power/LowPower": [
                "核对进入睡眠前的唤醒源、GPIO 电平和时钟源配置。",
                "确认唤醒后外设是否重新初始化。",
            ],
        }
        return common + module_map.get(owner, ["按模块归属继续补齐专项日志和最小复现工程。"])
