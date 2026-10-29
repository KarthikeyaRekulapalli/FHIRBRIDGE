"""Summarization entry points: build the configured provider once at startup,
then summarize explicitly selected records. No fallback to another provider."""
from __future__ import annotations

from ..config import AIConfig
from ..logging_config import get_logger
from ..models import PatientClinicalSummary
from .anthropic import AnthropicSummarizer
from .base import DISCLAIMER, SYSTEM_PROMPT, AIConfigError, AIError, Summarizer, build_facts, user_prompt
from .extractive import ExtractiveSummarizer, extractive_summary
from .ollama import OllamaSummarizer
from .openai_compat import OpenAICompatSummarizer
from .snowflake import SnowflakeSummarizer

log = get_logger(__name__)

PROVIDERS = {
    "extractive": lambda cfg: ExtractiveSummarizer(),
    "ollama": OllamaSummarizer,
    "openai_compat": OpenAICompatSummarizer,
    "anthropic": AnthropicSummarizer,
    "snowflake": SnowflakeSummarizer,
}


def build_summarizer(cfg: AIConfig) -> Summarizer:
    """Validate configuration and return the provider. Raises AIConfigError."""
    try:
        factory = PROVIDERS[cfg.provider]
    except KeyError:
        raise AIConfigError(f"AI_PROVIDER must be one of {', '.join(PROVIDERS)}") from None
    if cfg.max_output_tokens <= 0 or cfg.max_input_chars < 1000 or cfg.timeout <= 0:
        raise AIConfigError("AI_MAX_OUTPUT_TOKENS, AI_MAX_INPUT_CHARS (>=1000) and AI_TIMEOUT must be positive")
    return factory(cfg)


async def summarize(summarizer: Summarizer, per_source: list[PatientClinicalSummary],
                    max_input_chars: int) -> tuple[str, list[str]]:
    """Return (narrative, omitted notes). Raises AIError; never switches provider."""
    if isinstance(summarizer, ExtractiveSummarizer):
        return extractive_summary(per_source), []
    facts, omitted = build_facts(per_source, max_input_chars)
    log.info("summarizing %d record(s) with %s (%d chars, %d omission note(s))",
             len(per_source), summarizer.name, len(facts), len(omitted))
    text = await summarizer.complete(SYSTEM_PROMPT, user_prompt(facts))
    return text, omitted


__all__ = ["AIConfigError", "AIError", "DISCLAIMER", "Summarizer", "build_summarizer", "summarize"]
