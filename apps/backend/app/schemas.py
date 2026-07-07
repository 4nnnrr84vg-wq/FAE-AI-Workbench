from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Priority = Literal["P0", "P1", "P2", "P3"]


class Source(BaseModel):
    path: str
    line: int | None = None
    title: str = ""
    snippet: str = ""
    score: float = 0.0
    chunk_id: str = ""
    retrieval: str = ""
    matched_issue: str = ""


class RagIndexStatus(BaseModel):
    enabled: bool = True
    qdrant_ok: bool = False
    collection: str = ""
    collection_exists: bool = False
    indexed_points: int = 0
    indexed_files: int = 0
    embedding_mode: str = "local"
    vector_size: int = 0
    last_error: str = ""


class SdkVersionInfo(BaseModel):
    enabled: bool = False
    configured: bool = False
    version: str = ""
    ref: str = ""
    ref_type: str = ""
    commit_sha: str = ""
    commit_title: str = ""
    web_url: str = ""
    release_notes: str = ""
    matched_files: list[str] = Field(default_factory=list)
    error: str = ""


class AttachmentMeta(BaseModel):
    name: str
    content_type: str = "application/octet-stream"
    size: int | None = None
    url: str | None = None


class InboxParseRequest(BaseModel):
    text: str = ""
    source: str = "wechat"
    customer_hint: str = ""
    attachments: list[str] = Field(default_factory=list)
    chat_context: str = ""


class CustomerIssue(BaseModel):
    customer: str = ""
    product_model: str = ""
    sdk_version: str = ""
    firmware_version: str = ""
    hardware_model: str = ""
    symptom: str = ""
    error_keywords: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    priority: Priority = "P2"
    suggested_owner: str = "FAE"
    raw_text: str = ""
    confidence: float = 0.0


class KnowledgeQueryRequest(BaseModel):
    question: str
    product_model: str = ""
    sdk_version: str = ""
    firmware_version: str = ""
    project_path: str = ""
    top_k: int = 8


class KnowledgeAnswer(BaseModel):
    answer: str
    sources: list[Source] = Field(default_factory=list)
    query_terms: list[str] = Field(default_factory=list)
    used_llm: bool = False
    retrieval_mode: str = "file_scan"
    index_status: RagIndexStatus | None = None
    sdk_info: SdkVersionInfo | None = None


class SdkResolveRequest(BaseModel):
    sdk_version: str


class SdkResolveResponse(BaseModel):
    info: SdkVersionInfo


class RagReindexRequest(BaseModel):
    force: bool = True


class RagReindexResponse(BaseModel):
    ok: bool
    status: RagIndexStatus
    message: str = ""


class LogAnalyzeRequest(BaseModel):
    log_text: str
    product_model: str = ""
    sdk_version: str = ""
    firmware_version: str = ""
    top_k_sources: int = 6


class LogContext(BaseModel):
    line: int
    before: list[str] = Field(default_factory=list)
    current: str
    after: list[str] = Field(default_factory=list)


class LogAnalysis(BaseModel):
    key_error_lines: list[str] = Field(default_factory=list)
    error_codes: list[str] = Field(default_factory=list)
    module_owner: str = "Unknown"
    timeline: list[str] = Field(default_factory=list)
    contexts: list[LogContext] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    related_docs: list[Source] = Field(default_factory=list)
    checklist: list[str] = Field(default_factory=list)
    disclaimer: str = "初步排查假设生成器，不承诺自动定位根因。"


class ResponseDraftRequest(BaseModel):
    issue: CustomerIssue
    log_analysis: LogAnalysis | None = None
    knowledge: KnowledgeAnswer | None = None
    tone: Literal["normal", "concise", "formal"] = "normal"


class ResponseDraft(BaseModel):
    draft: str
    follow_up_questions: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    used_llm: bool = False


class TicketRequest(BaseModel):
    issue: CustomerIssue
    log_analysis: LogAnalysis | None = None
    knowledge: KnowledgeAnswer | None = None
    attempted_steps: list[str] = Field(default_factory=list)


class InternalTicket(BaseModel):
    title: str
    severity: Priority
    suggested_owner: str
    report: str
    fields: dict[str, Any] = Field(default_factory=dict)
    sources: list[Source] = Field(default_factory=list)


class WorkbenchRunRequest(BaseModel):
    customer_text: str = ""
    log_text: str = ""
    customer_hint: str = ""
    attachments: list[str] = Field(default_factory=list)
    question: str = ""
    project_path: str = ""
    sdk_version: str = ""


class WorkbenchRunResponse(BaseModel):
    issue: CustomerIssue
    knowledge: KnowledgeAnswer
    log_analysis: LogAnalysis
    response: ResponseDraft
    ticket: InternalTicket


class UploadResponse(BaseModel):
    file: AttachmentMeta
