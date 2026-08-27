"""Razorpay test-mode world seeder (FR-1.1).

Single responsibility: create the merchant world as REAL test-mode objects
(customers, one plan, subscriptions, payment links, invoices) and record every
created id in data/seed_registry.json. Idempotent: entities already in the
registry are never re-created; the registry is flushed after every create so a
crash mid-seed resumes cleanly.
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Any, Protocol

import yaml

REGISTRY_PATH = Path("data/seed_registry.json")
FIRST_NAMES = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Sana", "Vikram", "Anjali", "Imran"]
LAST_NAMES = ["Sharma", "Patel", "Reddy", "Khan", "Iyer", "Das", "Mehta", "Nair", "Singh"]


class RzpClient(Protocol):
    """The slice of the razorpay SDK client we use (also implemented by test fakes)."""

    customer: Any
    plan: Any
    subscription: Any
    order: Any
    invoice: Any


def synthetic_customer(idx: int) -> dict:
    """Deterministic synthetic PII — no real people, ever (C-6)."""
    r = random.Random(f"cust|{idx}")
    name = f"{r.choice(FIRST_NAMES)} {r.choice(LAST_NAMES)}"
    return {
        "name": name,
        "email": f"cust{idx:04d}@example.test",
        "contact": f"+9199900{idx:05d}",
        "fail_existing": "0",  # razorpay: return existing instead of erroring
    }


class Seeder:
    """Creates missing world entities against a Razorpay client, registry-first."""

    def __init__(self, client: RzpClient, cfg: dict, registry_path: Path = REGISTRY_PATH):
        self.client = client
        self.cfg = cfg["seed_entities"]
        self.path = registry_path
        self.registry: dict = (
            json.loads(registry_path.read_text()) if registry_path.exists() else {}
        )

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.registry, indent=1, sort_keys=True))

    def _ensure(self, kind: str, logical: str, create) -> None:
        """Create-if-absent, persist immediately (crash-safe idempotency).
        Rate limits get exponential backoff; other errors propagate."""
        bucket = self.registry.setdefault(kind, {})
        if logical in bucket:
            return
        for attempt in range(10):
            try:
                bucket[logical] = create()["id"]
                break
            except Exception as e:
                if "Too many requests" in str(e) and attempt < 9:
                    time.sleep(min(60, 2**attempt))
                    continue
                raise
        self._save()

    def run(self) -> dict:
        c = self.cfg
        for i in range(c["customers"]):
            self._ensure(
                "customers",
                f"cust_{i:04d}",
                lambda i=i: self.client.customer.create(synthetic_customer(i)),
            )
        # Subscriptions is a separately-activated Razorpay product; if this test
        # account doesn't have it yet, seed everything else and let an idempotent
        # re-run fill the gap after activation.
        try:
            self._ensure(
                "plan",
                "plan",
                lambda: self.client.plan.create(
                    {
                        "period": "monthly",
                        "interval": 1,
                        "item": {
                            "name": "Kirana+ Monthly",
                            "amount": c["plan_amount_inr"] * 100,
                            "currency": "INR",
                        },
                    }
                ),
            )
            plan_id = self.registry["plan"]["plan"]
            for i in range(1, c["subscriptions"] + 1):
                self._ensure(
                    "subscriptions",
                    f"sub_{i:04d}",
                    lambda: self.client.subscription.create(
                        {
                            "plan_id": plan_id,
                            "total_count": 12,
                            "customer_notify": 0,
                        }
                    ),
                )
        except Exception as e:  # noqa: BLE001 — section isolation, warned loudly below
            print(
                f"WARNING: plan/subscriptions skipped ({type(e).__name__}). Enable the "
                "Subscriptions product on this Razorpay test account, then re-run "
                "`make seed` to fill the gap. Events use sim_ ids meanwhile (SIMULATION.md)."
            )
        # L2 = checkout abandonment: the entity is an Order (created, unpaid).
        # NOT payment links — test mode caps those at 30 total, and the budget is
        # reserved for per-nudge links created on demand (FR-6.2).
        for i in range(1, c["orders"] + 1):
            r = random.Random(f"order|{i}")
            amt = r.randrange(c["order_amount_inr"]["min"], c["order_amount_inr"]["max"] + 1)
            self._ensure(
                "orders",
                f"order_{i:04d}",
                lambda amt=amt, i=i: self.client.order.create(
                    {
                        "amount": amt * 100,
                        "currency": "INR",
                        "receipt": f"order_{i:04d}",
                        "notes": {"context": f"Kirana+ storefront order #{i}"},
                    }
                ),
            )
        cust_ids = list(self.registry["customers"].values())
        for i in range(1, c["invoices"] + 1):
            r = random.Random(f"inv|{i}")
            lo, hi = c["invoice_amount_inr"]["min"], c["invoice_amount_inr"]["max"]
            amt = r.randrange(lo, hi + 1, 100)
            self._ensure(
                "invoices",
                f"inv_{i:04d}",
                lambda amt=amt, i=i, r=r: self.client.invoice.create(
                    {
                        "type": "invoice",
                        "customer_id": r.choice(cust_ids),
                        "currency": "INR",
                        "line_items": [
                            {"name": f"B2B services #{i}", "amount": amt * 100, "quantity": 1}
                        ],
                    }
                ),
            )
        return self.registry


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    key, secret = os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")
    if not key or not secret or not key.startswith("rzp_test_"):
        raise SystemExit(
            "Razorpay TEST-MODE keys required: set RAZORPAY_KEY_ID (rzp_test_...) and "
            "RAZORPAY_KEY_SECRET in .env (see .env.example). Live keys are refused."
        )
    import razorpay

    client = razorpay.Client(auth=(key, secret))
    cfg = yaml.safe_load(Path("config/sim_config.yaml").read_text())
    registry = Seeder(client, cfg).run()
    counts = {k: (len(v) if isinstance(v, dict) else 1) for k, v in registry.items()}
    print(f"seeded (idempotent): {counts} -> {REGISTRY_PATH}")


if __name__ == "__main__":
    main()
