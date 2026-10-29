"""Anthropic Messages API, directly over HTTP (no SDK). AI_BASE_URL may point at
a private gateway that fronts the API; the request shape is unchanged."""
from __future__ import annotations

from urllib.parse import urlparse

from ..config import AIConfig
from .base import AIConfigError, AIError, post_json


class AnthropicSummarizer:
    def __init__(self, cfg: AIConfig) -> None:
        if not cfg.api_key:
            raise AIConfigError("AI_API_KEY is required for AI_PROVIDER=anthropic")
        if not cfg.model:
            raise AIConfigError("AI_MODEL is required for AI_PROVIDER=anthropic (e.g. claude-sonnet-5-5)")
        self.cfg = cfg
        self.base_url = cfg.base_url or "https://api.anthropic.com"
        self.name = f"anthropic:{cfg.model}"
        self.data_destination = urlparse(self.base_url).netloc

    async def complete(self, system: str, user: str) -> str:
        data = await post_json(
            f"{self.base_url}/v1/messages", timeout=self.cfg.timeout,
            headers={"x-api-key": self.cfg.api_key, "anthropic-version": self.cfg.anthropic_version,
                     "Content-Type": "application/json"},
            body={
                "model": self.cfg.model, "max_tokens": self.cfg.max_output_tokens,
                "temperature": self.cfg.temperature, "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        parts = [b.get("text", "") for b in data.get("content") or [] if isinstance(b, dict) and b.get("type") == "text"]
        text = "".join(parts).strip()
        if not text:
            raise AIError("Anthropic returned no text content")
        return text
