# AI summarization providers

One provider is configured server-side (`AI_PROVIDER`) and validated at startup.
There is no per-request override and no automatic fallback: if the provider
fails, `/api/summary` returns 502 with a sanitized reason and the source records
remain available through `/api/records`.

| `AI_PROVIDER` | Protocol | Required | Facts are sent to |
|---|---|---|---|
| `extractive` | none (deterministic, in-process) | nothing | nowhere |
| `ollama` | Ollama `/api/chat` | `AI_MODEL`; `AI_BASE_URL` default `http://localhost:11434` | the Ollama host |
| `openai_compat` | OpenAI Chat Completions (`/chat/completions`) | `AI_BASE_URL` (ending in `/v1` for most servers), `AI_MODEL`, `AI_API_KEY` if the server needs one | `AI_BASE_URL` host (vLLM, LM Studio, OpenAI, HF router, a private gateway) |
| `anthropic` | Anthropic Messages API (`/v1/messages`) | `AI_API_KEY`, `AI_MODEL`; `AI_BASE_URL` for a private gateway (default `https://api.anthropic.com`) | that host |
| `snowflake` | Cortex `inference:complete` (SSE) | `AI_API_KEY` (PAT), `AI_MODEL`, `SNOWFLAKE_ACCOUNT` or `AI_BASE_URL` | your Snowflake account |

Shared settings: `AI_TIMEOUT` (s), `AI_MAX_OUTPUT_TOKENS`, `AI_MAX_INPUT_CHARS`,
`AI_TEMPERATURE`. The UI header and every summary display `provider` and
`data_destination` from `/api/config`.

## What is sent

Only the records the user selected and confirmed, rendered as plain text per
source (patient demographics, conditions, medications, allergies, vital signs,
encounters, plus notes for failed or partial fetches). The text sits inside
`<patient_records>` delimiters and the system prompt instructs the model to treat
it as data and ignore instruction-like content. If the rendering exceeds
`AI_MAX_INPUT_CHARS`, list items are cut from the end and each cut is reported in
the response as `omitted` and shown in the UI.

## Output contract

The system prompt asks for three labelled sections: documented facts (with
source attribution), conflicts between sources, missing or unavailable
information; no invented details; under 250 words. The response carries the
disclaimer shown in the UI.

## Adding a provider

Implement a class with `name`, `data_destination` and `async complete(system,
user) -> str` in `backend/app/ai/`, raise `AIConfigError` from `__init__` for
missing settings and `AIError` for runtime failures, and register it in
`PROVIDERS` in `backend/app/ai/__init__.py`. Use a separate adapter whenever the
authentication, payload, streaming or response shape differs; reuse
`openai_compat` when the protocol genuinely matches.
