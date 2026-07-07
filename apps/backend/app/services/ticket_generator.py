from __future__ import annotations

from app.schemas import InternalTicket, TicketRequest


class TicketGenerator:
    def generate(self, req: TicketRequest) -> InternalTicket:
        issue = req.issue
        log = req.log_analysis
        knowledge = req.knowledge
        title = self._title(issue)
        key_logs = "\n".join(log.key_error_lines[:8]) if log else "未提供"
        hypotheses = "\n".join(f"- {item}" for item in (log.hypotheses if log else [])) or "- 待补充日志后判断"
        missing = "\n".join(f"- {item}" for item in issue.missing_info) or "- 暂无"
        attempted = "\n".join(f"- {item}" for item in req.attempted_steps) or "- 客户暂未提供"
        sources = []
        if knowledge:
            sources.extend(knowledge.sources)
        if log:
            sources.extend(log.related_docs)

        source_lines = "\n".join(
            f"- 《{src.title or src.path}》：{src.matched_issue or '相关资料'}"
            for src in sources[:6]
        ) or "- 暂无"

        report = f"""# {title}

## 问题摘要
{issue.symptom or "未明确描述"}

## 客户环境
- 客户: {issue.customer or "未识别"}
- 产品/硬件型号: {issue.product_model or issue.hardware_model or "未提供"}
- SDK 版本: {issue.sdk_version or "未提供"}
- 固件版本: {issue.firmware_version or "未提供"}
- 附件: {", ".join(issue.attachments) if issue.attachments else "未提供"}

## 关键日志
{key_logs}

## 相关资料
{source_lines}

## 初步判断
{hypotheses}

## 已尝试步骤
{attempted}

## 需要研发确认
{missing}

## 建议分配模块
{issue.suggested_owner}

## 严重程度
{issue.priority}
"""
        fields = {
            "customer": issue.customer,
            "product_model": issue.product_model,
            "sdk_version": issue.sdk_version,
            "firmware_version": issue.firmware_version,
            "error_keywords": issue.error_keywords,
            "module_owner": log.module_owner if log else issue.suggested_owner,
        }
        return InternalTicket(
            title=title,
            severity=issue.priority,
            suggested_owner=issue.suggested_owner,
            report=report.strip(),
            fields=fields,
            sources=sources[:10],
        )

    def _title(self, issue) -> str:
        model = issue.product_model or issue.hardware_model or "未知型号"
        symptom = issue.symptom or "客户问题待分析"
        return f"[{issue.priority}] {model} - {symptom[:40]}"
