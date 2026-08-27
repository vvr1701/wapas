"""Diagnosis engine — deterministic tier (FR-3.1, FR-3.2).

Single responsibility: map a revenue event to exactly one root cause from the
closed taxonomy, with confidence and source. Rules cover the structured cases;
anything unmapped is UNKNOWN (routed to escalation by policy) — never guessed.
The LLM tier for fuzzy free-text (FR-3.3, P1) plugs in behind the same output
shape later.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agent.cases import CaseState, transition
from agent.detector import RevenueEvent
from ledger.db import RecoveryCaseRow

ERROR_MAP_PATH = Path("config/error_map.yaml")


class RootCause(StrEnum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    CARD_EXPIRED = "CARD_EXPIRED"
    MANDATE_PAUSED_CANCELLED = "MANDATE_PAUSED_CANCELLED"
    BANK_GATEWAY_DOWNTIME = "BANK_GATEWAY_DOWNTIME"
    AUTH_ABANDONED = "AUTH_ABANDONED"
    PRICE_HESITATION = "PRICE_HESITATION"
    PAYMENT_METHOD_FRICTION = "PAYMENT_METHOD_FRICTION"
    INVOICE_DISPUTED = "INVOICE_DISPUTED"
    INVOICE_FORGOTTEN = "INVOICE_FORGOTTEN"
    CLIENT_CASHFLOW_DELAY = "CLIENT_CASHFLOW_DELAY"
    UNKNOWN = "UNKNOWN"


class Diagnosis(BaseModel):
    """Every case carries exactly one of these (FR-3.2)."""

    root_cause: RootCause
    confidence: float
    source: Literal["rule", "llm"]


def load_error_map(path: Path = ERROR_MAP_PATH) -> dict[str, str]:
    return yaml.safe_load(path.read_text())["by_error_reason"]


def diagnose(event: RevenueEvent, error_map: dict[str, str]) -> Diagnosis:
    """Table-driven, deterministic. UNKNOWN is a first-class honest answer."""
    if event.category == "L1":
        cause = error_map.get(event.error_reason or "")
        if cause is None:
            return Diagnosis(root_cause=RootCause.UNKNOWN, confidence=0.0, source="rule")
        return Diagnosis(root_cause=RootCause(cause), confidence=0.95, source="rule")
    if event.category == "L2":
        # OTP/auth attempted then dropped vs never attempted (price hesitation).
        if event.auth_attempted:
            return Diagnosis(root_cause=RootCause.AUTH_ABANDONED, confidence=0.85, source="rule")
        return Diagnosis(root_cause=RootCause.PRICE_HESITATION, confidence=0.6, source="rule")
    # L3: dispute markers come from customer replies (FR-3.3, later phase);
    # rules default an overdue invoice to FORGOTTEN at moderate confidence.
    return Diagnosis(root_cause=RootCause.INVOICE_FORGOTTEN, confidence=0.6, source="rule")


def diagnose_case(
    session: Session,
    case: RecoveryCaseRow,
    event: RevenueEvent,
    error_map: dict[str, str],
) -> Diagnosis:
    """Apply a diagnosis to a case: fields + DETECTED->DIAGNOSED, audit-paired."""
    d = diagnose(event, error_map)
    case.root_cause = d.root_cause
    case.diagnosis_confidence = d.confidence
    case.diagnosis_source = d.source
    transition(
        session,
        case,
        CaseState.DIAGNOSED,
        payload={"root_cause": d.root_cause, "confidence": d.confidence, "source": d.source},
    )
    return d
