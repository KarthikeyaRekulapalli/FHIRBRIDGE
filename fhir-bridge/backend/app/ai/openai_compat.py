"""OpenAI Chat Completions protocol. Covers OpenAI, vLLM, LM Studio, llama.cpp,
Ollama's /v1 endpoint, the Hugging Face router and any private gateway that
speaks the same protocol."""
from __future__ import annotations

from urllib.parse import urlparse

from ..config import AIConfig
from .base import AIConfigError, AIError, post_json


class OpenAICompatSummarizer:
    def __init__(self, cfg: AIConfig) -> None:
        if not cfg.base_url:
            raise AIConfigError("AI_BASE_URL is required for AI_PROVIDER=openai_compat (e.g. https://host/v1)")
        if not cfg.model:
            raise AIConfigError("AI_MODEL is required for AI_PROVIDER=openai_compat")
        self.cfg = cfg
        self.name = f"openai_compat:{cfg.model}"
        self.data_destination = urlparse(cfg.base_url).netloc

    async def complete(self, system: str, user: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        data = await post_json(
            f"{self.cfg.base_url}/chat/completions", headers=headers, timeout=self.cfg.timeout,
            body={
                "model": self.cfg.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": self.cfg.temperature,
                "max_tokens": self.cfg.max_output_tokens,
            },
        )
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError("AI provider response had no choices[0].message.content") from exc
        if not isinstance(text, str) or not text.strip():
            raise AIError("AI provider returned an empty summary")
        return text.strip()
