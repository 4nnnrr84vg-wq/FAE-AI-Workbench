from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.services.knowledge_base import KnowledgeBase  # noqa: E402
from app.services.llm import LLMClient  # noqa: E402


def main() -> int:
    settings = get_settings()
    kb = KnowledgeBase(settings, LLMClient(settings))
    status = kb.reindex()
    print(f"qdrant_ok: {status.qdrant_ok}")
    print(f"collection: {status.collection}")
    print(f"indexed_points: {status.indexed_points}")
    print(f"indexed_files: {status.indexed_files}")
    print(f"embedding_mode: {status.embedding_mode}")
    print(f"vector_size: {status.vector_size}")
    if status.last_error:
        print(f"last_error: {status.last_error}")
    return 0 if status.qdrant_ok and status.indexed_points > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
