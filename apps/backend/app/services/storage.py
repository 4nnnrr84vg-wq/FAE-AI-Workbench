from __future__ import annotations

import io
import re
import uuid
from pathlib import Path

from app.core.config import Settings
from app.schemas import AttachmentMeta


class AttachmentStorage:
    def __init__(self, settings: Settings):
        self.settings = settings

    def save_bytes(self, filename: str, content: bytes, content_type: str) -> AttachmentMeta:
        safe_name = self._safe_name(filename)
        if self.settings.object_storage_mode.lower() == "s3":
            stored = self._try_save_s3(safe_name, content, content_type)
            if stored:
                return stored
        return self._save_local(safe_name, content, content_type)

    def _try_save_s3(self, filename: str, content: bytes, content_type: str) -> AttachmentMeta | None:
        try:
            from minio import Minio

            endpoint = self.settings.s3_endpoint.replace("https://", "").replace("http://", "").rstrip("/")
            secure = self.settings.s3_endpoint.startswith("https://")
            client = Minio(
                endpoint,
                access_key=self.settings.s3_access_key,
                secret_key=self.settings.s3_secret_key,
                secure=secure,
            )
            if not client.bucket_exists(self.settings.s3_bucket):
                client.make_bucket(self.settings.s3_bucket)
            object_name = f"{uuid.uuid4().hex}/{filename}"
            client.put_object(
                self.settings.s3_bucket,
                object_name,
                io.BytesIO(content),
                length=len(content),
                content_type=content_type,
            )
            return AttachmentMeta(
                name=filename,
                content_type=content_type,
                size=len(content),
                url=f"{self.settings.s3_endpoint.rstrip('/')}/{self.settings.s3_bucket}/{object_name}",
            )
        except Exception:
            return None

    def _save_local(self, filename: str, content: bytes, content_type: str) -> AttachmentMeta:
        self.settings.storage_root.mkdir(parents=True, exist_ok=True)
        target = Path(self.settings.storage_root) / f"{uuid.uuid4().hex}_{filename}"
        target.write_bytes(content)
        return AttachmentMeta(
            name=filename,
            content_type=content_type,
            size=len(content),
            url=str(target),
        )

    def _safe_name(self, filename: str) -> str:
        name = Path(filename or "attachment.bin").name
        name = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]", "_", name)
        return name[:160] or "attachment.bin"
