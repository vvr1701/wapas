"""Failure event generator (FR-1.2).

Single responsibility: emit a fully seed-determined batch of revenue-at-risk
events across L1/L2/L3 using Razorpay's error-code taxonomy (starter map,
PRD Appendix A). Entity IDs come from data/seed_registry.json when the world
has been seeded against real test-mode APIs; otherwise deterministic synthetic
IDs are used (disclosed in SIMULATION.md).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

# Fixed simulated "now" so batches are reproducible (never datetime.now()).
SIM_NOW = datetime(2026, 8, 27, 11, 0, tzinfo=UTC)

# Error taxonomy: error_reason values verified against Razorpay's card error
# docs (razorpay.com/docs/errors/payments/cards/, checked Aug 27 2026):
# insufficient_funds, card_expired, gateway_technical_error are documented
# reasons. mandate_cancelled follows the starter map (PRD Appendix A) — the
# e-mandate reason catalog is not publicly enumerated the same way.
L1_ERRORS: dict[str, dict[str, str]] = {
    "insufficient_funds": {
        "error_code": "BAD_REQUEST_ERROR",
        "error_reason": "insufficient_funds",
        "error_description": "Customer's account lacked adequate balance",
    },
    "card_expired": {
        "error_code": "BAD_REQUEST_ERROR",
        "error_reason": "card_expired",
        "error_description": "Payment failed because the card has expired",
    },
    "mandate_paused_cancelled": {
        "error_code": "BAD_REQUEST_ERROR",
        "error_reason": "mandate_cancelled",
        "error_description": "Charge failed because the e-mandate is paused or cancelled",
    },
    "bank_gateway_downtime": {
        "error_code": "GATEWAY_ERROR",
        "error_reason": "gateway_technical_error",
        "error_description": "Partner bank downtime preventing payment processing",
    },
}


class SimEvent(BaseModel):
    """One revenue-at-risk event as injected into ingestion (source=simulator)."""

    event_id: str
    category: Literal["L1", "L2", "L3"]
    customer_id: str
    entity_type: Literal["subscription", "order", "invoice"]
    entity_id: str
    amount_inr: int
    occurred_at: datetime
    # L1 only
    error_code: str | None = None
    error_reason: str | None = None
    error_description: str | None = None
    # L2 only
    auth_attempted: bool | None = None
    # L3 only
    due_date: datetime | None = None


def _load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _entity_id(registry: dict, kind: str, logical: str) -> str:
    """Real Razorpay id when seeded, else deterministic synthetic id."""
    return registry.get(kind, {}).get(logical) or f"sim_{logical}"


def _weighted(r: random.Random, mix: dict[str, float]) -> str:
    return r.choices(list(mix), weights=list(mix.values()), k=1)[0]


def generate_batch(seed: int, cfg: dict, registry: dict) -> list[SimEvent]:
    """Deterministic batch: same (seed, config, registry) -> identical events."""
    r = random.Random(f"batch|{seed}")
    b, ents = cfg["batch"], cfg["seed_entities"]
    n_cust = ents["customers"]
    events: list[SimEvent] = []
    counters = {"subscription": 0, "order": 0, "invoice": 0}
    for i in range(b["size"]):
        cat = _weighted(r, b["category_mix"])
        cid = f"cust_{r.randrange(n_cust):04d}"
        occurred = SIM_NOW - timedelta(minutes=r.randrange(0, 72 * 60))
        if cat == "L1":
            n = counters["subscription"] = counters["subscription"] % ents["subscriptions"] + 1
            err = L1_ERRORS[_weighted(r, b["l1_error_mix"])]
            events.append(
                SimEvent(
                    event_id=f"evt_{i:04d}",
                    category="L1",
                    customer_id=cid,
                    entity_type="subscription",
                    entity_id=_entity_id(registry, "subscriptions", f"sub_{n:04d}"),
                    amount_inr=ents["plan_amount_inr"],
                    occurred_at=occurred,
                    **err,
                )
            )
        elif cat == "L2":
            n = counters["order"] = counters["order"] % ents["orders"] + 1
            lo, hi = ents["order_amount_inr"]["min"], ents["order_amount_inr"]["max"]
            events.append(
                SimEvent(
                    event_id=f"evt_{i:04d}",
                    category="L2",
                    customer_id=cid,
                    entity_type="order",
                    entity_id=_entity_id(registry, "orders", f"order_{n:04d}"),
                    amount_inr=r.randrange(lo, hi + 1),
                    occurred_at=occurred,
                    auth_attempted=r.random() < b["l2_auth_attempted_share"],
                )
            )
        else:
            n = counters["invoice"] = counters["invoice"] % ents["invoices"] + 1
            lo, hi = ents["invoice_amount_inr"]["min"], ents["invoice_amount_inr"]["max"]
            od = b["l3_days_overdue"]
            events.append(
                SimEvent(
                    event_id=f"evt_{i:04d}",
                    category="L3",
                    customer_id=cid,
                    entity_type="invoice",
                    entity_id=_entity_id(registry, "invoices", f"inv_{n:04d}"),
                    amount_inr=r.randrange(lo, hi + 1, 100),
                    occurred_at=occurred,
                    due_date=SIM_NOW - timedelta(days=r.randint(od["min"], od["max"])),
                )
            )
    return events


def batch_hash(events: list[SimEvent]) -> str:
    """Canonical content hash of a batch — the reproducibility proof (FR-1.2 AC)."""
    payload = json.dumps([e.model_dump(mode="json") for e in events], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def main() -> None:
    p = argparse.ArgumentParser(description="Generate a seeded revenue-at-risk batch")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--config", type=Path, default=Path("config/sim_config.yaml"))
    p.add_argument("--registry", type=Path, default=Path("data/seed_registry.json"))
    p.add_argument("--out", type=Path, default=None)
    a = p.parse_args()
    registry = json.loads(a.registry.read_text()) if a.registry.exists() else {}
    events = generate_batch(a.seed, _load_config(a.config), registry)
    out = a.out or Path(f"data/events_seed{a.seed}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([e.model_dump(mode="json") for e in events], indent=1))
    print(f"events={len(events)} out={out} batch_hash={batch_hash(events)}")


if __name__ == "__main__":
    main()
