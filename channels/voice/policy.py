"""Voice conversation policy (FR-7.2) — deterministic rails around the LLM.

Single responsibility: enforce every FR-7.2 behavior in CODE. The disclosure
line is prepended by code, stop/dispute/abuse are detected and handled by code,
negotiation bounds are validated by code, and the LLM only generates polite
Hinglish language inside those rails. A hostile or malformed model can annoy a
customer at worst — it can never change state, grant a discount, or skip a rule.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel

from channels.nudge import tone_lint

DISCLOSURE = (
    "Namaste! Main Kirana+ ki taraf se ek AI assistant bol rahi hoon, "
    "payment reminder ke liye. Kya abhi baat karna theek rahega?"
)
STOP_SCRIPT = (
    "Bilkul, main abhi call band kar rahi hoon aur aapko dobara call nahi aayega. Dhanyavaad."
)
DISPUTE_SCRIPT = (
    "Samajh gayi — agar payment ho chuki hai toh koi baat nahi. Main ise verify "
    "karwati hoon, aur hamari team jald hi confirm karegi. Dhanyavaad!"
)
ABUSE_SCRIPT = (
    "Main samajh sakti hoon ki aap pareshaan hain. Main abhi call yahin khatam "
    "karti hoon; hamari team se ek insaan aapse sampark karega. Dhanyavaad."
)
FALLBACK_LINE = "Maaf kijiye, main theek se samajh nahi payi. Kya aap dobara bata sakte hain?"

MAX_PROMISE_DAYS = 14  # FR-7.2(3)
MIN_PROMISE_PCT = 50

_DISPUTE_PATTERNS = [
    r"\b(already|pehle)\s+(paid|pay|bhej)",
    r"\bpay\s+kar\s+(diya|chuka|chuki)\b",
    r"\bmaine\s+.{0,20}pay\b",
    r"\bpayment\s+(ho\s+gaya|ho\s+chuki|done)\b",
    r"\bgalat\s+(bill|invoice|amount)\b",
    r"\bdispute\b",
]
_ABUSE_PATTERNS = [
    r"\b(bhenchod|madarchod|chutiya|kamina|saala|harami)\b",
    r"\bidiot\b.*\bidiot\b",  # sustained, not a single slip
    r"\bi will (find|hurt|kill)\b",
    r"\bshut up\b.*\bshut up\b",
]
_SUSPICIOUS_PATTERNS = [
    r"ignore (your|all|previous) instructions",
    r"\bdeveloper mode\b",
    r"\bsystem\s*:",
    r"\bmark (this|it) as paid\b",
    r"\bcancel all\b",
    r"\bwaive\b",
    r"\byou are now\b",
]
# LLM-output rail: any % or "discount/waive/maaf" language is beyond authority.
_FORBIDDEN_OUTPUT = [r"\d+\s*%", r"\bdiscount\b", r"\bwaive[rd]?\b", r"\bmaaf kar\b"]


class Intent(StrEnum):
    STOP = "STOP"
    DISPUTE = "DISPUTE"
    ABUSE = "ABUSE"
    OTHER = "OTHER"


class CallFacts(BaseModel):
    case_id: int
    customer_id: str
    customer_name: str
    amount_inr: int
    due_date: str
    context: str = "pending invoice"
    today: str


class AgentTurn(BaseModel):
    text: str
    end_call: bool = False
    trigger_opt_out: bool = False
    trigger_dispute_check: bool = False
    trigger_abuse_escalation: bool = False
    suspicious_input: bool = False
    llm_used: bool = False


class CallSession(BaseModel):
    """Text-mode state of one call; the audio layer wraps this unchanged (FR-7.4)."""

    facts: CallFacts
    transcript: list[dict[str, str]] = []
    disclosed: bool = False
    ended: bool = False


def classify_intent(text: str) -> Intent:
    from agent.guardrails import detect_stop_intent

    low = text.lower()
    if detect_stop_intent(low):
        return Intent.STOP
    if any(re.search(p, low) for p in _ABUSE_PATTERNS):
        return Intent.ABUSE
    if any(re.search(p, low) for p in _DISPUTE_PATTERNS):
        return Intent.DISPUTE
    return Intent.OTHER


def is_suspicious(text: str) -> bool:
    low = text.lower()
    return any(re.search(p, low) for p in _SUSPICIOUS_PATTERNS)


def output_violates_rails(text: str) -> bool:
    low = text.lower()
    return bool(tone_lint(low)) or any(re.search(p, low) for p in _FORBIDDEN_OUTPUT)


def promise_within_bounds(amount_inr: int, days_out: int, amount_due_inr: int) -> bool:
    """FR-7.2(3): dates ≤14 days, amounts ≥50% — beyond that, human review."""
    return 0 < days_out <= MAX_PROMISE_DAYS and amount_inr >= amount_due_inr * MIN_PROMISE_PCT / 100


LlmFn = Callable[[CallSession, str], str]  # (session, customer_text) -> reply text


def respond(call: CallSession, customer_text: str, llm: LlmFn | None) -> AgentTurn:
    """One conversation turn. Rails first, LLM only for open conversation, and
    LLM output is validated before it is spoken. Never raises on model failure."""
    if call.ended:
        return AgentTurn(text="", end_call=True)
    call.transcript.append({"role": "customer", "text": customer_text})
    suspicious = is_suspicious(customer_text)
    intent = classify_intent(customer_text)

    if intent == Intent.STOP:
        turn = AgentTurn(
            text=STOP_SCRIPT, end_call=True, trigger_opt_out=True, suspicious_input=suspicious
        )
    elif intent == Intent.ABUSE:
        turn = AgentTurn(
            text=ABUSE_SCRIPT,
            end_call=True,
            trigger_abuse_escalation=True,
            suspicious_input=suspicious,
        )
    elif intent == Intent.DISPUTE:
        turn = AgentTurn(
            text=DISPUTE_SCRIPT,
            end_call=True,
            trigger_dispute_check=True,
            suspicious_input=suspicious,
        )
    else:
        text, used = FALLBACK_LINE, False
        if llm is not None:
            try:
                candidate = llm(call, customer_text)
                if candidate and not output_violates_rails(candidate):
                    text, used = candidate.strip(), True
            except Exception:
                pass  # deterministic fallback below — the call never crashes (NFR-7)
        turn = AgentTurn(text=text, suspicious_input=suspicious, llm_used=used)

    if not call.disclosed:  # FR-7.2(1): disclosure ALWAYS first, prepended by code
        if DISCLOSURE not in turn.text:
            turn.text = f"{DISCLOSURE} {turn.text}".strip()
        call.disclosed = True

    call.transcript.append({"role": "agent", "text": turn.text})
    call.ended = turn.end_call
    return turn
