"""Ollama native /api/chat (local inference). Data stays on the host running Ollama."""
from __future__ import annotations

from urllib.parse import urlparse

from ..config import AIConfig
from .base import AIConfigError, AIError, post_json


class OllamaSummarizer:
    def __init__(self, cfg: AIConfig) -> None:
        if not cfg.model:
            raise AIConfigError("AI_MODEL is required for AI_PROVIDER=ollama (e.g. llama3.2)")
        self.cfg = cfg
        self.base_url = cfg.base_url or "http://localhost:11434"
        self.name = f"ollama:{cfg.model}"
        self.data_destination = urlparse(self.base_url).netloc

    async def complete(self, system: str, user: str) -> str:
        data = await post_json(
            f"{self.base_url}/api/chat", headers={"Content-Type": "application/json"}, timeout=self.cfg.timeout,
            body={
                "model": self.cfg.model, "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": {"temperature": self.cfg.temperature, "num_predict": self.cfg.max_output_tokens},
            },
        )
        text = (data.get("message") or {}).get("content") if isinstance(data.get("message"), dict) else None
        if not isinstance(text, str) or not text.strip():
            raise AIError("Ollama returned an empty summary")
        return text.strip()
