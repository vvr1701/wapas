"""Promise-to-pay extraction (FR-7.3): fuzzy in, structured out, gated before
it touches state.

Single responsibility: turn a call transcript into a validated promise or an
honest "needs human review". Claude (Opus 5) proposes strict
JSON; pydantic validates; deterministic rails reject low confidence and absurd
values (date >30d out, amount <=0 or >2x due). Invalid JSON gets exactly one
retry, then human review — extraction NEVER auto-records on shaky ground.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from agent.llm import EXTRACTION_MODEL, LlmUnavailable, call_claude, load_prompt

MIN_CONFIDENCE = 0.7
MAX_DAYS_OUT = 30
MAX_AMOUNT_MULTIPLE = 2


class ExtractedPromise(BaseModel):
    promise: bool
    amount_inr: int
    date: str | None  # YYYY-MM-DD
    conditions: str | None = None
    confidence: float


class PromiseDecision(BaseModel):
    """What the system does with an extraction: auto-record or human review."""

    extracted: ExtractedPromise | None
    auto_record: bool
    review_reason: str | None = None


def validate_rails(
    extracted: ExtractedPromise, *, amount_due_inr: int, call_date: date
) -> PromiseDecision:
    """Deterministic rails (FR-7.3): low confidence or absurd values -> human
    review, never auto-recorded."""
    if not extracted.promise:
        return PromiseDecision(extracted=extracted, auto_record=False, review_reason=None)
    if extracted.confidence < MIN_CONFIDENCE:
        return PromiseDecision(
            extracted=extracted, auto_record=False, review_reason="low_confidence"
        )
    if extracted.amount_inr <= 0 or extracted.amount_inr > amount_due_inr * MAX_AMOUNT_MULTIPLE:
        return PromiseDecision(
            extracted=extracted, auto_record=False, review_reason="absurd_amount"
        )
    if extracted.date is None:
        return PromiseDecision(extracted=extracted, auto_record=False, review_reason="no_date")
    promised = date.fromisoformat(extracted.date)
    if promised <= call_date or promised > call_date + timedelta(days=MAX_DAYS_OUT):
        return PromiseDecision(extracted=extracted, auto_record=False, review_reason="absurd_date")
    return PromiseDecision(extracted=extracted, auto_record=True)


def _parse_json(text: str) -> ExtractedPromise:
    match = re.search(r"\{.*\}", text, re.DOTALL)  # tolerate stray prose around JSON
    if not match:
        raise ValueError("no JSON object in response")
    return ExtractedPromise(**json.loads(match.group()))


def extract_promise(
    session: Session | None,
    transcript: list[dict[str, str]],
    *,
    amount_due_inr: int,
    call_date: date,
) -> PromiseDecision:
    """LLM extraction with one retry, then human review (§6.2). Never raises."""
    text = "\n".join(f"{t['role'].upper()}: {t['text']}" for t in transcript)
    prompt, prompt_hash = load_prompt(
        "promise_extraction.txt",
        amount_inr=amount_due_inr,
        call_date=call_date.isoformat(),
        transcript=text,
    )
    for _attempt in range(2):  # 1 retry on invalid output, per §6.2
        try:
            raw = call_claude(
                session,
                purpose="promise_extraction",
                prompt_file="promise_extraction.txt",
                prompt=prompt,
                prompt_hash=prompt_hash,
                model=EXTRACTION_MODEL,
            )
            extracted = _parse_json(raw)
        except LlmUnavailable:
            return PromiseDecision(
                extracted=None, auto_record=False, review_reason="llm_unavailable"
            )
        except (ValueError, ValidationError, json.JSONDecodeError):
            continue
        return validate_rails(extracted, amount_due_inr=amount_due_inr, call_date=call_date)
    return PromiseDecision(extracted=None, auto_record=False, review_reason="invalid_output")
