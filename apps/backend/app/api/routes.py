from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from app.core.config import get_settings
from app.schemas import (
    InboxParseRequest,
    InternalTicket,
    KnowledgeAnswer,
    KnowledgeQueryRequest,
    LogAnalysis,
    LogAnalyzeRequest,
    RagIndexStatus,
    RagReindexRequest,
    RagReindexResponse,
    ResponseDraft,
    ResponseDraftRequest,
    SdkResolveRequest,
    SdkResolveResponse,
    TicketRequest,
    UploadResponse,
    WorkbenchRunRequest,
    WorkbenchRunResponse,
)
from app.services.inbox_extractor import InboxExtractor
from app.services.gitlab_sdk import GitLabSdkResolver
from app.services.knowledge_base import KnowledgeBase
from app.services.llm import LLMClient
from app.services.log_analyzer import LogAnalyzer
from app.services.response_generator import ResponseGenerator
from app.services.storage import AttachmentStorage
from app.services.ticket_generator import TicketGenerator


router = APIRouter()
settings = get_settings()
llm = LLMClient(settings)
kb = KnowledgeBase(settings, llm)
sdk_resolver = GitLabSdkResolver(settings)
inbox = InboxExtractor()
log_analyzer = LogAnalyzer(kb)
response_generator = ResponseGenerator(llm)
ticket_generator = TicketGenerator()
storage = AttachmentStorage(settings)


@router.get("/health")
def health() -> dict:
    rag_status = kb.status()
    return {
        "ok": True,
        "model_api": llm.enabled,
        "rag": rag_status.model_dump(),
        "knowledge_root": str(settings.knowledge_root),
        "knowledge_root_exists": settings.knowledge_root.exists(),
        "storage_root": str(settings.storage_root),
        "object_storage_mode": settings.object_storage_mode,
        "postgres_configured": bool(settings.database_url),
        "redis_configured": bool(settings.redis_url),
        "qdrant_url": settings.qdrant_url,
        "gitlab_sdk_configured": sdk_resolver.configured,
    }


@router.post("/api/inbox/parse")
def parse_inbox(req: InboxParseRequest):
    return inbox.parse(req)


@router.post("/api/kb/query", response_model=KnowledgeAnswer)
def query_kb(req: KnowledgeQueryRequest) -> KnowledgeAnswer:
    return kb.query(req)


@router.post("/api/sdk/resolve", response_model=SdkResolveResponse)
def resolve_sdk(req: SdkResolveRequest) -> SdkResolveResponse:
    return SdkResolveResponse(info=sdk_resolver.resolve(req.sdk_version))


@router.get("/api/kb/status", response_model=RagIndexStatus)
def kb_status() -> RagIndexStatus:
    return kb.status()


@router.post("/api/kb/reindex", response_model=RagReindexResponse)
def reindex_kb(req: RagReindexRequest | None = None) -> RagReindexResponse:
    status = kb.reindex()
    ok = status.qdrant_ok and status.collection_exists and status.indexed_points > 0
    message = (
        f"indexed {status.indexed_points} chunks from {status.indexed_files} files"
        if ok
        else status.last_error or "RAG index was not built"
    )
    return RagReindexResponse(ok=ok, status=status, message=message)


@router.post("/api/logs/analyze", response_model=LogAnalysis)
def analyze_log(req: LogAnalyzeRequest) -> LogAnalysis:
    return log_analyzer.analyze(req)


@router.post("/api/responses/draft", response_model=ResponseDraft)
def draft_response(req: ResponseDraftRequest) -> ResponseDraft:
    return response_generator.draft(req)


@router.post("/api/tickets/generate", response_model=InternalTicket)
def generate_ticket(req: TicketRequest) -> InternalTicket:
    return ticket_generator.generate(req)


@router.post("/api/workbench/run", response_model=WorkbenchRunResponse)
def run_workbench(req: WorkbenchRunRequest) -> WorkbenchRunResponse:
    issue = inbox.parse(
        InboxParseRequest(
            text=req.customer_text,
            customer_hint=req.customer_hint,
            attachments=req.attachments,
        )
    )
    question = req.question or issue.symptom or req.customer_text
    sdk_version = req.sdk_version or issue.sdk_version
    knowledge = kb.query(
        KnowledgeQueryRequest(
            question=question,
            product_model=issue.product_model,
            sdk_version=sdk_version,
            firmware_version=issue.firmware_version,
            project_path=req.project_path,
            top_k=8,
        )
    )
    log_analysis = log_analyzer.analyze(
        LogAnalyzeRequest(
            log_text=req.log_text or req.customer_text,
            product_model=issue.product_model,
            sdk_version=sdk_version,
            firmware_version=issue.firmware_version,
            top_k_sources=6,
        )
    )
    response = response_generator.draft(
        ResponseDraftRequest(issue=issue, log_analysis=log_analysis, knowledge=knowledge)
    )
    ticket = ticket_generator.generate(
        TicketRequest(issue=issue, log_analysis=log_analysis, knowledge=knowledge)
    )
    return WorkbenchRunResponse(
        issue=issue,
        knowledge=knowledge,
        log_analysis=log_analysis,
        response=response,
        ticket=ticket,
    )


@router.post("/api/attachments", response_model=UploadResponse)
async def upload_attachment(file: UploadFile = File(...)) -> UploadResponse:
    content = await file.read()
    saved = storage.save_bytes(
        file.filename,
        content,
        file.content_type or "application/octet-stream",
    )
    return UploadResponse(file=saved)
