from __future__ import annotations

import re
from pathlib import Path

from app.core.config import Settings
from app.schemas import KnowledgeAnswer, KnowledgeQueryRequest, RagIndexStatus, Source
from app.services.document_loader import DocumentLoader
from app.services.embeddings import EmbeddingClient
from app.services.gitlab_sdk import GitLabSdkResolver, extract_sdk_version
from app.services.llm import LLMClient
from app.services.project_context import ProjectContext
from app.services.rag_store import RagStore
from app.services.text_utils import normalize_space, tokenize, unique_keep_order


ISSUE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("浅睡/低功耗唤醒配置", ("浅睡", "低功耗", "lightsleep", "sleep", "wake", "唤醒", "pwr")),
    ("深睡/关机唤醒配置", ("深睡", "deepsleep", "power_on", "关机", "rxd")),
    ("OTA/升级失败排查", ("ota", "升级", "boot", "crc", "image", "flash")),
    ("BLE 连接/广播/GATT 问题", ("ble", "蓝牙", "广播", "连接", "gatt", "gap", "pair", "bond")),
    ("2.4G 通信/射频配置", ("2.4g", "射频", "rf", "信道", "发射功率")),
    ("GPIO/UART/外设驱动配置", ("gpio", "uart", "rxd", "txd", "i2c", "spi", "adc", "timer")),
    ("WDT/看门狗配置", ("wdt", "watchdog", "看门狗", "喂狗")),
    ("NVDS/Flash 参数存储", ("nvds", "flash", "存储", "非易失")),
    ("API 函数使用说明", ("api", "函数", "xc_", "_config", "_init")),
]


class KnowledgeBase:
    def __init__(self, settings: Settings, llm: LLMClient):
        self.settings = settings
        self.llm = llm
        self.embeddings = EmbeddingClient(settings)
        self.rag = RagStore(settings, self.embeddings)
        self.loader = DocumentLoader(settings)
        self.project_context = ProjectContext()
        self.gitlab_sdk = GitLabSdkResolver(settings)

    def status(self) -> RagIndexStatus:
        return self.rag.status()

    def reindex(self) -> RagIndexStatus:
        return self.rag.reindex()

    def query(self, req: KnowledgeQueryRequest) -> KnowledgeAnswer:
        terms = self._terms(req)
        query = self._query_text(req, terms)
        sdk_version = req.sdk_version or extract_sdk_version(req.question)
        sdk_info = self.gitlab_sdk.resolve(sdk_version) if sdk_version else None
        sources = self.rag.search(query, req.top_k)
        retrieval_mode = "qdrant_vector" if sources else "file_scan"
        if not sources:
            sources = self.keyword_search(query, req.top_k)
        else:
            sources = self._dedupe_sources(sources, req.top_k)
        project_sources = self.project_context.search(req.project_path, query, max(4, req.top_k // 2))
        if project_sources:
            sources = self._merge_sources(sources, project_sources, req.top_k + len(project_sources))
            retrieval_mode = f"{retrieval_mode}+project_scan"
        sdk_source = self.gitlab_sdk.to_source(sdk_info) if sdk_info else None
        if sdk_source:
            sources = self._merge_sources([sdk_source], sources, req.top_k + len(project_sources) + 1)
            retrieval_mode = f"{retrieval_mode}+gitlab_sdk"
        sources = self._annotate_sources(sources, query)
        answer, used_llm = self._build_answer(req, terms, sources, retrieval_mode)
        return KnowledgeAnswer(
            answer=answer,
            sources=sources,
            query_terms=terms,
            used_llm=used_llm,
            retrieval_mode=retrieval_mode,
            index_status=self.status(),
            sdk_info=sdk_info,
        )

    def search(self, query: str, top_k: int = 8) -> list[Source]:
        sources = self.rag.search(query, top_k)
        if sources:
            return self._annotate_sources(self._dedupe_sources(sources, top_k), query)
        return self.keyword_search(query, top_k)

    def keyword_search(self, query: str, top_k: int = 8) -> list[Source]:
        terms = tokenize(query, 24)
        if not terms and query.strip():
            terms = [query.strip()]
        low_terms = [term.lower() for term in terms if term]
        hits: list[Source] = []
        for chunk in self.loader.iter_chunks():
            score = self._score_chunk(chunk.title, chunk.text, low_terms)
            if score <= 0:
                continue
            hits.append(
                Source(
                    path=str(chunk.path),
                    line=chunk.line_start,
                    title=chunk.title,
                    snippet=self._best_snippet(chunk.text, terms),
                    score=score,
                    chunk_id=chunk.chunk_id,
                    retrieval="file_scan",
                )
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return self._annotate_sources(self._dedupe_sources(hits, top_k), query)

    def _terms(self, req: KnowledgeQueryRequest) -> list[str]:
        raw = " ".join(
            part
            for part in [
                req.question,
                req.product_model,
                req.sdk_version,
                req.firmware_version,
            ]
            if part
        )
        return tokenize(raw, 16)

    def _query_text(self, req: KnowledgeQueryRequest, terms: list[str]) -> str:
        parts = [
            req.question,
            req.product_model,
            req.sdk_version,
            req.firmware_version,
            " ".join(terms),
        ]
        return "\n".join(part for part in parts if part).strip()

    def _score_chunk(self, title: str, text: str, low_terms: list[str]) -> float:
        if not low_terms:
            return 0.0
        title_low = title.lower()
        text_low = text.lower()
        score = 0.0
        for term in low_terms:
            if term in title_low:
                score += 4.0
            count = text_low.count(term)
            if count:
                score += min(6.0, count * 1.2)
        for phrase in ("错误", "失败", "异常", "配置", "唤醒", "升级", "初始化"):
            if phrase in text and phrase in " ".join(low_terms):
                score += 0.5
        return score

    def _best_snippet(self, text: str, terms: list[str], width: int = 420) -> str:
        compact = normalize_space(re.sub(r"<[^>]+>", " ", text))
        if not compact:
            return ""
        low = compact.lower()
        positions = [low.find(term.lower()) for term in terms if term and low.find(term.lower()) >= 0]
        if not positions:
            return compact[:width]
        center = min(positions)
        start = max(0, center - width // 3)
        end = min(len(compact), start + width)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(compact) else ""
        return f"{prefix}{compact[start:end]}{suffix}"

    def _annotate_sources(self, sources: list[Source], query: str) -> list[Source]:
        annotated: list[Source] = []
        for source in sources:
            issue = source.matched_issue or self._infer_issue(source.title, source.snippet, query)
            annotated.append(source.model_copy(update={"matched_issue": issue}))
        return annotated

    def _infer_issue(self, title: str, snippet: str, query: str = "") -> str:
        haystack = f"{title}\n{snippet}\n{query}".lower()
        for issue, keys in ISSUE_RULES:
            if any(key.lower() in haystack for key in keys):
                return issue
        name = Path(title).stem or "当前资料"
        return f"与“{name}”相关的问题"

    def _build_answer(
        self,
        req: KnowledgeQueryRequest,
        terms: list[str],
        sources: list[Source],
        retrieval_mode: str,
    ) -> tuple[str, bool]:
        if not sources:
            return (
                "当前资料库未命中明确资料。\n"
                "初步建议：请补充更具体的芯片型号、SDK 版本、错误码、完整日志，"
                "或把对应手册/FAQ/Release Notes/历史案例放入 reference/documents 后重新检索。"
            ), False

        lines = [f"检索模式：{retrieval_mode}"]
        doc_sources = [source for source in sources if source.retrieval not in {"project_scan", "gitlab_sdk"}]
        project_sources = [source for source in sources if source.retrieval == "project_scan"]
        sdk_sources = [source for source in sources if source.retrieval == "gitlab_sdk"]
        if sdk_sources:
            lines.append("SDK 版本关联：")
            self._append_source_lines(lines, sdk_sources[:2])
        if doc_sources:
            lines.append("命中资料：")
            self._append_source_lines(lines, doc_sources[:6])
        if project_sources:
            lines.append("命中工程：")
            self._append_source_lines(lines, project_sources[:6])

        ai_summary = self._llm_summary(req, sources)
        if ai_summary:
            lines.append("简要结论：")
            lines.append(ai_summary)

        lines.append("初步方案：")
        for item in self._solution_steps(req.question, sources):
            lines.append(f"- {item}")

        missing = self._missing_info(req, terms)
        if req.project_path and not project_sources:
            missing.append("工程路径已填写，但未检索到明显相关实现；请确认路径是否是客户工程根目录")
        if missing:
            lines.append("还需要补充：")
            for item in unique_keep_order(missing):
                lines.append(f"- {item}")
        return "\n".join(lines), bool(ai_summary)

    def _append_source_lines(self, lines: list[str], sources: list[Source]) -> None:
        for idx, source in enumerate(sources[:6], 1):
            doc_name = source.title or source.path
            loc = f"第 {source.line} 行" if source.line else "位置未标注"
            lines.append(f"{idx}. 《{doc_name}》({loc})")
            lines.append(f"   对应问题：{source.matched_issue}")
            lines.append(f"   依据：{source.snippet}")

    def _llm_summary(self, req: KnowledgeQueryRequest, sources: list[Source]) -> str:
        if not self.llm.enabled or not sources:
            return ""
        evidence = "\n".join(
            f"[{idx}] {src.title or src.path}:{src.line or ''} {src.matched_issue} - {src.snippet}"
            for idx, src in enumerate(sources[:10], 1)
        )
        result = self.llm.complete(
            system=(
                "你是 FAE 助手。只能根据给定资料和工程命中回答。"
                "输出 2 到 4 句中文，直接说重点，必须引用编号，例如 [1]。"
                "不要寒暄，不要承诺根因，不要编造未给出的信息。"
            ),
            context=f"问题：{req.question}\n\n依据：\n{evidence}",
            user="基于这些依据给出简洁结论。",
            temperature=0.1,
        )
        return result.text.strip() if result.text else ""

    def _solution_steps(self, question: str, sources: list[Source]) -> list[str]:
        text = f"{question}\n" + "\n".join(f"{s.matched_issue}\n{s.snippet}" for s in sources)
        low = text.lower()
        steps: list[str] = []
        if any(k in low for k in ("浅睡", "lightsleep", "wake", "唤醒", "低功耗")):
            steps.extend(
                [
                    "先按命中资料核对进入浅睡前的唤醒源配置、GPIO 电平/边沿配置和中断回调。",
                    "确认唤醒后相关外设是否需要重新初始化，避免只处理深睡而漏掉浅睡路径。",
                ]
            )
        if any(k in low for k in ("ota", "升级", "crc", "boot", "flash")):
            steps.extend(
                [
                    "先核对升级包、Flash 分区、CRC/镜像命名和升级前后版本兼容说明。",
                    "要求客户提供升级前版本、升级文件名和完整 boot log。",
                ]
            )
        if any(k in low for k in ("wifi", "wlan", "dhcp", "ssid")):
            steps.extend(
                [
                    "先核对 WiFi 初始化顺序、旧配置迁移、SSID/加密方式和 DHCP 阶段日志。",
                    "让客户确认是否清除过旧配置，并提供初始化参数。",
                ]
            )
        if any(k in low for k in ("ble", "蓝牙", "gatt", "gap", "广播", "连接")):
            steps.extend(
                [
                    "先按资料核对广播、连接参数、绑定信息和 GATT 读写流程。",
                    "对比升级前后 SDK/Release Notes 中 BLE 相关变更。",
                ]
            )
        if not steps:
            steps.append("先按命中资料逐项核对配置、调用顺序、版本差异和异常前后日志。")
        return unique_keep_order(steps)[:4]

    def _missing_info(self, req: KnowledgeQueryRequest, terms: list[str]) -> list[str]:
        missing: list[str] = []
        if not req.product_model and not any(re.search(r"\bXC\d{4,5}\b", term, re.I) for term in terms):
            missing.append("芯片/硬件型号")
        if not req.sdk_version:
            missing.append("SDK 版本")
        if not req.firmware_version and any(k in req.question for k in ("固件", "升级", "版本")):
            missing.append("当前固件版本和升级前版本")
        if any(k in req.question.lower() for k in ("log", "日志", "失败", "error", "failed")):
            missing.append("完整日志，至少包含异常前后 30 秒")
        return unique_keep_order(missing)

    def _dedupe_sources(self, hits: list[Source], top_k: int) -> list[Source]:
        deduped: list[Source] = []
        seen: set[str] = set()
        seen_docs: set[str] = set()
        for hit in hits:
            key = hit.chunk_id or f"{hit.path}:{hit.line}:{hit.snippet[:80]}"
            doc_key = hit.title or hit.path
            if key in seen or doc_key in seen_docs:
                continue
            seen.add(key)
            seen_docs.add(doc_key)
            deduped.append(hit)
            if len(deduped) >= top_k:
                break
        return deduped

    def _merge_sources(self, first: list[Source], second: list[Source], top_k: int) -> list[Source]:
        merged: list[Source] = []
        seen: set[str] = set()
        for hit in [*first, *second]:
            key = hit.chunk_id or f"{hit.path}:{hit.line}:{hit.snippet[:80]}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(hit)
            if len(merged) >= top_k:
                break
        return merged
