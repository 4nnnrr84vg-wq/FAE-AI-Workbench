from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file(PROJECT_ROOT / ".env.web")
_load_env_file(PROJECT_ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _secret_env(name: str, default: str = "") -> str:
    value = _env(name, "")
    if value in {"replace-with-your-api-key", "YOUR_API_KEY"}:
        return default
    return value or default


@dataclass(frozen=True)
class Settings:
    app_name: str = "FAE AI Workbench"
    environment: str = _env("APP_ENV", "local")
    cors_origins: str = _env(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )

    database_url: str = _env(
        "DATABASE_URL",
        "postgresql+psycopg://fae:fae@localhost:5432/fae_workbench",
    )
    redis_url: str = _env("REDIS_URL", "redis://localhost:6379/0")
    qdrant_url: str = _env("QDRANT_URL", "http://localhost:6333")
    qdrant_collection: str = _env("QDRANT_COLLECTION", "fae_knowledge_chunks")
    qdrant_timeout_sec: int = int(_env("QDRANT_TIMEOUT_SEC", "5") or "5")

    s3_endpoint: str = _env("S3_ENDPOINT", "http://localhost:9000")
    s3_access_key: str = _env("S3_ACCESS_KEY", "minioadmin")
    s3_secret_key: str = _env("S3_SECRET_KEY", "minioadmin")
    s3_bucket: str = _env("S3_BUCKET", "fae-attachments")
    object_storage_mode: str = _env("OBJECT_STORAGE_MODE", "local")
    storage_root: Path = Path(_env("STORAGE_ROOT", str(PROJECT_ROOT / ".web_mvp_storage")))

    knowledge_root: Path = Path(
        _env("KNOWLEDGE_ROOT", str(PROJECT_ROOT / "reference" / "documents"))
    )
    file_library_root: Path = Path(
        _env("FILE_LIBRARY_ROOT", str(PROJECT_ROOT / "file_library"))
    )

    model_api_base_url: str = _env(
        "MODEL_API_BASE_URL",
        _env("OPENAI_BASE_URL", "https://api.deepseek.com/v1"),
    )
    model_api_key: str = _secret_env("MODEL_API_KEY", _secret_env("DEEPSEEK_API_KEY", ""))
    model_api_model: str = _env("MODEL_API_MODEL", "deepseek-chat")
    model_timeout_sec: int = int(_env("MODEL_TIMEOUT_SEC", "45") or "45")

    rag_enabled: bool = _env("RAG_ENABLED", "true").lower() not in {"0", "false", "no"}
    rag_auto_index: bool = _env("RAG_AUTO_INDEX", "false").lower() in {"1", "true", "yes"}
    rag_chunk_chars: int = int(_env("RAG_CHUNK_CHARS", "1200") or "1200")
    rag_chunk_overlap: int = int(_env("RAG_CHUNK_OVERLAP", "180") or "180")

    embedding_mode: str = _env("EMBEDDING_MODE", "local").lower()
    embedding_api_base_url: str = _env("EMBEDDING_API_BASE_URL", "")
    embedding_api_key: str = _secret_env("EMBEDDING_API_KEY", "")
    embedding_api_model: str = _env("EMBEDDING_API_MODEL", "text-embedding-3-small")
    embedding_vector_size: int = int(_env("EMBEDDING_VECTOR_SIZE", "384") or "384")
    embedding_timeout_sec: int = int(_env("EMBEDDING_TIMEOUT_SEC", "45") or "45")

    max_index_file_bytes: int = int(_env("MAX_INDEX_FILE_BYTES", "30000000") or "30000000")

    gitlab_base_url: str = _env("GITLAB_BASE_URL", "")
    gitlab_token: str = _secret_env("GITLAB_TOKEN", "")
    gitlab_project: str = _env("GITLAB_PROJECT", "")
    gitlab_timeout_sec: int = int(_env("GITLAB_TIMEOUT_SEC", "12") or "12")
    gitlab_ref_patterns: str = _env(
        "GITLAB_REF_PATTERNS",
        "{version},v{plain},sdk-{version},sdk-{plain},release/{version},release/{plain}",
    )
    gitlab_release_note_paths: str = _env(
        "GITLAB_RELEASE_NOTE_PATHS",
        "ReleaseNotes.md,RELEASE_NOTES.md,CHANGELOG.md,CHANGELOG.txt,docs/ReleaseNotes.md,docs/release_notes.md",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


def get_settings() -> Settings:
    return Settings()
