from __future__ import annotations

import uuid
from typing import Any

from app.core.config import Settings
from app.schemas import RagIndexStatus, Source
from app.services.document_loader import DocumentChunk, DocumentLoader
from app.services.embeddings import EmbeddingClient


class RagStore:
    def __init__(self, settings: Settings, embeddings: EmbeddingClient):
        self.settings = settings
        self.embeddings = embeddings
        self.loader = DocumentLoader(settings)

    def status(self) -> RagIndexStatus:
        base = RagIndexStatus(
            enabled=self.settings.rag_enabled,
            collection=self.settings.qdrant_collection,
            embedding_mode=self.embeddings.mode,
            vector_size=self.embeddings.vector_size,
        )
        if not self.settings.rag_enabled:
            return base
        try:
            client = self._client()
            info = client.get_collection(self.settings.qdrant_collection)
            points = int(getattr(info, "points_count", 0) or 0)
            return base.model_copy(
                update={
                    "qdrant_ok": True,
                    "collection_exists": True,
                    "indexed_points": points,
                }
            )
        except Exception as exc:
            return base.model_copy(update={"last_error": str(exc)})

    def reindex(self) -> RagIndexStatus:
        if not self.settings.rag_enabled:
            return self.status()
        chunks = self.loader.iter_chunks(refresh=True)
        if not chunks:
            return self.status().model_copy(update={"last_error": "no readable knowledge chunks found"})

        client = self._client()
        vectors = self._embed_chunks(chunks)
        if not vectors:
            return self.status().model_copy(update={"last_error": "embedding returned no vectors"})
        vector_size = len(vectors[0])

        from qdrant_client.http import models

        if client.collection_exists(self.settings.qdrant_collection):
            client.delete_collection(self.settings.qdrant_collection)
        client.create_collection(
            collection_name=self.settings.qdrant_collection,
            vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
        )
        points = []
        for chunk, vector in zip(chunks, vectors):
            points.append(
                models.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.chunk_id)),
                    vector=vector,
                    payload=self._payload(chunk),
                )
            )

        for idx in range(0, len(points), 64):
            client.upsert(
                collection_name=self.settings.qdrant_collection,
                points=points[idx : idx + 64],
                wait=True,
            )

        status = self.status()
        unique_files = len({str(chunk.path) for chunk in chunks})
        return status.model_copy(
            update={
                "qdrant_ok": True,
                "collection_exists": True,
                "indexed_points": len(points),
                "indexed_files": unique_files,
                "vector_size": vector_size,
                "last_error": "",
            }
        )

    def search(self, query: str, top_k: int = 8) -> list[Source]:
        if not self.settings.rag_enabled or not query.strip():
            return []
        status = self.status()
        if not status.qdrant_ok or not status.collection_exists or status.indexed_points <= 0:
            if not self.settings.rag_auto_index:
                return []
            try:
                status = self.reindex()
            except Exception:
                return []
            if not status.qdrant_ok or not status.collection_exists or status.indexed_points <= 0:
                return []

        try:
            client = self._client()
            query_vector = self.embeddings.embed_texts([query])[0]
            if hasattr(client, "search"):
                results = client.search(
                    collection_name=self.settings.qdrant_collection,
                    query_vector=query_vector,
                    limit=max(1, top_k),
                    with_payload=True,
                )
            else:
                response = client.query_points(
                    collection_name=self.settings.qdrant_collection,
                    query=query_vector,
                    limit=max(1, top_k),
                    with_payload=True,
                )
                results = getattr(response, "points", response)
        except Exception:
            return []

        sources: list[Source] = []
        for item in results:
            payload = item.payload or {}
            sources.append(
                Source(
                    path=str(payload.get("path") or ""),
                    line=self._int_or_none(payload.get("line")),
                    title=str(payload.get("title") or ""),
                    snippet=str(payload.get("snippet") or payload.get("text") or "")[:500],
                    score=float(getattr(item, "score", 0.0) or 0.0),
                    chunk_id=str(payload.get("chunk_id") or ""),
                    retrieval="qdrant_vector",
                )
            )
        return sources

    def _client(self):
        from qdrant_client import QdrantClient

        return QdrantClient(url=self.settings.qdrant_url, timeout=self.settings.qdrant_timeout_sec)

    def _embed_chunks(self, chunks: list[DocumentChunk]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for idx in range(0, len(chunks), 32):
            batch = chunks[idx : idx + 32]
            vectors.extend(self.embeddings.embed_texts([chunk.text for chunk in batch]))
        return vectors

    def _payload(self, chunk: DocumentChunk) -> dict[str, Any]:
        return {
            "chunk_id": chunk.chunk_id,
            "path": str(chunk.path),
            "title": chunk.title,
            "line": chunk.line_start,
            "line_end": chunk.line_end,
            "snippet": chunk.text[:500],
            "text": chunk.text,
        }

    def _int_or_none(self, value: Any) -> int | None:
        try:
            if value is None:
                return None
            return int(value)
        except Exception:
            return None
