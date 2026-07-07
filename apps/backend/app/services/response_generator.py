from __future__ import annotations

from app.schemas import ResponseDraft, ResponseDraftRequest, Source
from app.services.llm import LLMClient
from app.services.text_utils import unique_keep_order


class ResponseGenerator:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def draft(self, req: ResponseDraftRequest) -> ResponseDraft:
        sources = self._sources(req)
        missing = self._missing(req)
        ai_draft = self._llm_draft(req, sources, missing)
        if ai_draft:
            return ResponseDraft(
                draft=ai_draft,
                follow_up_questions=missing,
                sources=sources,
                used_llm=True,
            )

        return ResponseDraft(
            draft=self._fallback_draft(req, sources, missing),
            follow_up_questions=missing,
            sources=sources,
            used_llm=False,
        )

    def _llm_draft(self, req: ResponseDraftRequest, sources: list[Source], missing: list[str]) -> str:
        if not self.llm.enabled:
            return ""
        evidence = "\n".join(
            f"[{idx}] {src.title or src.path}:{src.line or ''} {src.retrieval} {src.matched_issue} - {src.snippet}"
            for idx, src in enumerate(sources[:10], 1)
        )
        if req.log_analysis:
            log_text = "\n".join(
                [
                    "日志假设:",
                    "\n".join(req.log_analysis.hypotheses[:3]),
                    "关键错误:",
                    "\n".join(req.log_analysis.key_error_lines[:3]),
                ]
            )
        else:
            log_text = ""
        result = self.llm.complete(
            system=(
                "你是 FAE。生成可直接发给客户的中文短回复。"
                "风格要求：简洁、高效、说重点，不要客套，不要官方长文。"
                "必须基于给定资料/工程/日志依据；没有依据的内容不要说。"
                "结构固定为：已查到、建议先处理、还需补充。"
                "总长度控制在 220 字以内。"
            ),
            context=(
                f"客户现象：{req.issue.symptom}\n"
                f"客户环境：型号={req.issue.product_model or req.issue.hardware_model}, "
                f"SDK={req.issue.sdk_version}, 固件={req.issue.firmware_version}\n"
                f"依据：\n{evidence or '无明确资料/工程命中'}\n\n"
                f"{log_text}\n"
                f"需补充：{'; '.join(missing)}"
            ),
            user="生成客户回复。",
            temperature=0.15,
        )
        return result.text.strip() if result.text else ""

    def _fallback_draft(self, req: ResponseDraftRequest, sources: list[Source], missing: list[str]) -> str:
        lines: list[str] = []
        symptom = req.issue.symptom.strip()
        lines.append(f"先按“{symptom}”排查。" if symptom else "先按当前现象做初步排查。")

        doc_lines = self._doc_lines(sources)
        if doc_lines:
            lines.append("")
            lines.append("已查到：")
            lines.extend(doc_lines)

        solution = self._solution(req)
        if solution:
            lines.append("")
            lines.append("建议先处理：")
            lines.extend(f"{idx}. {item}" for idx, item in enumerate(solution, 1))

        if missing:
            lines.append("")
            lines.append("还需补充：")
            lines.extend(f"{idx}. {item}" for idx, item in enumerate(missing, 1))
        return "\n".join(lines).strip()

    def _doc_lines(self, sources: list[Source]) -> list[str]:
        lines: list[str] = []
        seen: set[str] = set()
        for source in sources:
            doc = source.title or source.path
            if not doc or doc in seen:
                continue
            seen.add(doc)
            issue = source.matched_issue or "相关问题"
            prefix = "工程" if source.retrieval == "project_scan" else "资料"
            loc = f"第 {source.line} 行" if source.line else "片段"
            lines.append(f"- {prefix}《{doc}》：{issue}（{loc}）")
            if len(lines) >= 4:
                break
        return lines

    def _solution(self, req: ResponseDraftRequest) -> list[str]:
        candidates: list[str] = []
        if req.log_analysis:
            if req.log_analysis.hypotheses:
                candidates.append(req.log_analysis.hypotheses[0])
            candidates.extend(req.log_analysis.checklist[:2])
        if req.knowledge and req.knowledge.sources:
            text = "\n".join(f"{s.matched_issue}\n{s.snippet}" for s in req.knowledge.sources)
            low = text.lower()
            if any(k in low for k in ("浅睡", "lightsleep", "wake", "唤醒", "低功耗")):
                candidates.append("核对浅睡前唤醒源、GPIO 电平/边沿、中断回调和唤醒后外设恢复流程。")
            if any(k in low for k in ("ota", "升级", "crc", "boot", "flash")):
                candidates.append("核对升级包、Flash 分区、CRC/镜像命名和升级前后版本兼容说明。")
            if any(k in low for k in ("wifi", "wlan", "dhcp", "ssid")):
                candidates.append("核对 WiFi 初始化顺序、旧配置迁移、SSID/加密方式和 DHCP 阶段日志。")
            if any(k in low for k in ("ble", "蓝牙", "gatt", "gap", "广播", "连接")):
                candidates.append("核对 BLE 广播、连接参数、绑定信息和 GATT 读写流程。")
        if not candidates:
            candidates.extend(
                [
                    "确认 SDK/固件/硬件型号是否与资料一致。",
                    "按异常前后日志定位第一个错误点，再对照资料检查配置和调用顺序。",
                ]
            )
        return unique_keep_order(candidates)[:4]

    def _missing(self, req: ResponseDraftRequest) -> list[str]:
        missing: list[str] = []
        missing.extend(req.issue.missing_info)
        if req.log_analysis:
            missing.extend(req.log_analysis.missing_info)
        return unique_keep_order(missing)[:6]

    def _sources(self, req: ResponseDraftRequest) -> list[Source]:
        sources: list[Source] = []
        if req.knowledge:
            sources.extend(req.knowledge.sources)
        if req.log_analysis:
            sources.extend(req.log_analysis.related_docs)
        out: list[Source] = []
        seen: set[str] = set()
        for source in sources:
            key = source.chunk_id or f"{source.path}:{source.line}:{source.snippet[:60]}"
            if key in seen:
                continue
            seen.add(key)
            out.append(source)
            if len(out) >= 10:
                break
        return out
