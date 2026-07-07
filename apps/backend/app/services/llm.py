from __future__ import annotations

import json
from dataclasses import dataclass

import requests

from app.core.config import Settings


@dataclass
class LLMResult:
    text: str
    error: str = ""


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.model_api_base_url and self.settings.model_api_key)

    def complete(
        self,
        *,
        system: str,
        user: str,
        context: str = "",
        temperature: float = 0.2,
    ) -> LLMResult:
        if not self.enabled:
            return LLMResult("", "MODEL_API_BASE_URL or MODEL_API_KEY is not configured")

        url = self.settings.model_api_base_url.rstrip("/") + "/chat/completions"
        messages = [{"role": "system", "content": system}]
        if context:
            messages.append({"role": "user", "content": context})
        messages.append({"role": "user", "content": user})
        payload = {
            "model": self.settings.model_api_model,
            "messages": messages,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.model_api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(
                url,
                headers=headers,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout=self.settings.model_timeout_sec,
            )
            resp.raise_for_status()
            data = resp.json()
            return LLMResult(data["choices"][0]["message"]["content"].strip())
        except Exception as exc:
            return LLMResult("", str(exc))
