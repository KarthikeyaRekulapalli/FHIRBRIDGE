"""Snowflake Cortex `inference:complete` REST API (server-sent events).
Inference runs inside the configured Snowflake account."""
from __future__ import annotations

import json

import httpx

from ..config import AIConfig
from .base import AIConfigError, AIError


class SnowflakeSummarizer:
    def __init__(self, cfg: AIConfig) -> None:
        if not cfg.api_key:
            raise AIConfigError("AI_API_KEY (programmatic access token) is required for AI_PROVIDER=snowflake")
        if not cfg.model:
            raise AIConfigError("AI_MODEL is required for AI_PROVIDER=snowflake")
        if not cfg.base_url and not cfg.snowflake_account:
            raise AIConfigError("SNOWFLAKE_ACCOUNT (or AI_BASE_URL) is required for AI_PROVIDER=snowflake")
        self.cfg = cfg
        host = cfg.base_url or f"https://{cfg.snowflake_account}.snowflakecomputing.com"
        self.url = f"{host}/api/v2/cortex/inference:complete"
        self.name = f"snowflake:{cfg.model}"
        self.data_destination = host.removeprefix("https://").removeprefix("http://")

    async def complete(self, system: str, user: str) -> str:
        body = {
            "model": self.cfg.model, "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_output_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        headers = {"Authorization": f"Bearer {self.cfg.api_key}", "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        out: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=self.cfg.timeout) as client:
                async with client.stream("POST", self.url, json=body, headers=headers) as resp:
                    if resp.status_code != 200:
                        raise AIError(f"Snowflake returned HTTP {resp.status_code}")
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload in ("", "[DONE]"):
                            continue
                        try:
                            chunk = json.loads(payload)
                            delta = chunk["choices"][0].get("delta", {}).get("content")
                        except (json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError):
                            continue
                        if delta:
                            out.append(delta)
        except httpx.TimeoutException as exc:
            raise AIError("Snowflake timed out") from exc
        except httpx.TransportError as exc:
            raise AIError(f"Snowflake unreachable ({type(exc).__name__})") from exc
        text = "".join(out).strip()
        if not text:
            raise AIError("Snowflake returned an empty summary")
        return text
