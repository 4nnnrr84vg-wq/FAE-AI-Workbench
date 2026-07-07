from __future__ import annotations

import hashlib
import json
import math
import re

import requests

from app.core.config import Settings


class EmbeddingClient:
    """Embedding provider for RAG.

    `EMBEDDING_MODE=local` uses a deterministic local token vectorizer so the
    knowledge base can run offline. Configure an embedding API for higher recall
    quality in delivery environments.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def mode(self) -> str:
        if (
            self.settings.embedding_mode == "api"
            and self.settings.embedding_api_base_url
            and self.settings.embedding_api_key
        ):
            return "api"
        return "local"

    @property
    def vector_size(self) -> int:
        return max(32, int(self.settings.embedding_vector_size))

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.mode == "api":
            return self._embed_api(texts)
        return [self._embed_local(text) for text in texts]

    def _embed_api(self, texts: list[str]) -> list[list[float]]:
        url = self.settings.embedding_api_base_url.rstrip("/") + "/embeddings"
        payload = {
            "model": self.settings.embedding_api_model,
            "input": texts,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.embedding_api_key}",
            "Content-Type": "application/json",
        }
        resp = requests.post(
            url,
            headers=headers,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=self.settings.embedding_timeout_sec,
        )
        resp.raise_for_status()
        data = resp.json()
        rows = sorted(data["data"], key=lambda item: item.get("index", 0))
        vectors = [row["embedding"] for row in rows]
        if not vectors:
            raise RuntimeError("embedding API returned no vectors")
        return vectors

    def _embed_local(self, text: str) -> list[float]:
        size = self.vector_size
        vec = [0.0] * size
        tokens = self._tokens(text)
        if not tokens:
            return vec
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8", errors="ignore"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % size
            weight = 1.0
            if "_" in token or token.startswith("0x") or token.isupper():
                weight = 1.8
            vec[idx] += weight
        norm = math.sqrt(sum(item * item for item in vec))
        if norm <= 0:
            return vec
        return [item / norm for item in vec]

    def _tokens(self, text: str) -> list[str]:
        raw = text or ""
        words = re.findall(
            r"0x[0-9a-fA-F]+|[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,8}|\d+\.\d+(?:\.\d+)?",
            raw,
        )
        lowered = [word.lower() for word in words]

        compact = re.sub(r"\s+", "", raw)
        chinese = re.findall(r"[\u4e00-\u9fff]+", compact)
        for block in chinese:
            for n in (2, 3, 4):
                lowered.extend(block[i : i + n] for i in range(0, max(0, len(block) - n + 1)))

        return lowered[:6000]
