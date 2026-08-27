"""LLM call layer (§6.2).

Single responsibility: every Claude call goes through call_claude(), which loads
the prompt from agent/prompts/, logs prompt_hash/model/tokens/latency/cost to
llm_calls, and never lets a model failure crash the system — errors surface as
LlmUnavailable for the caller's deterministic fallback. Model roster per the
decided stack: Sonnet 5 converses, Opus 5 extracts, Haiku 4.5 classifies.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ledger.db import LlmCallRow

PROMPTS_DIR = Path(__file__).parent / "prompts"

CONVERSATION_MODEL = "claude-sonnet-5"
EXTRACTION_MODEL = "claude-opus-5"
CLASSIFY_MODEL = "claude-haiku-4-5"

# USD per 1M tokens (input, output) — README cost table is computed from these.
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (3.0, 15.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


class LlmUnavailable(Exception):
    """Raised on any API failure; callers fall back deterministically (NFR-7)."""


def load_prompt(name: str, **fields: object) -> tuple[str, str]:
    """Returns (rendered_prompt, sha256_of_template)."""
    template = (PROMPTS_DIR / name).read_text()
    return template.format(**fields), hashlib.sha256(template.encode()).hexdigest()


def call_claude(
    session: Session | None,
    *,
    purpose: str,
    prompt_file: str,
    prompt: str,
    prompt_hash: str,
    model: str,
    max_tokens: int = 1024,
) -> str:
    """One logged Claude call. Returns the text response; raises LlmUnavailable
    on any failure after the SDK's own retries.

    Note: sampling params (temperature) are removed on current Claude models —
    the PRD's "temperature 0 for extraction" intent is served by strict JSON
    schemas + deterministic validation rails instead (documented in BUILD_LOG)."""
    started = time.monotonic()
    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:  # noqa: BLE001 — missing creds, network, API: all degrade the same
        _log(session, purpose, prompt_file, prompt_hash, model, 0, 0, started, False)
        raise LlmUnavailable(str(e)) from e
    text = "".join(b.text for b in response.content if b.type == "text")
    _log(
        session,
        purpose,
        prompt_file,
        prompt_hash,
        model,
        response.usage.input_tokens,
        response.usage.output_tokens,
        started,
        valid=bool(text),
    )
    if not text:
        raise LlmUnavailable(f"empty response (stop_reason={response.stop_reason})")
    return text


def _log(
    session: Session | None,
    purpose: str,
    prompt_file: str,
    prompt_hash: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    started: float,
    valid: bool,
) -> None:
    if session is None:
        return
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    session.add(
        LlmCallRow(
            purpose=purpose,
            prompt_file=prompt_file,
            prompt_hash=prompt_hash,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=int((time.monotonic() - started) * 1000),
            cost_usd=tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out,
            valid_output=valid,
            ts=datetime.now(UTC).isoformat(),
        )
    )
    session.flush()
