"""Deliver a signed payment.captured webhook to the local console (FR-2.3 demo).

Razorpay can't reach localhost, so delivery is local — but the code path is the
production one: HMAC-SHA256 signature verified, then observe_payment, which
flips a fully-paid case to RECOVERED. Usage:

    uv run python -m scripts.demo_webhook <case_id> [amount_inr]
"""

import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

import requests
from sqlalchemy.orm import Session

from ledger.db import RecoveryCaseRow, get_engine


def main() -> None:
    case_id = int(sys.argv[1])
    with Session(get_engine(Path("data/demo.db"))) as db:
        case = db.get(RecoveryCaseRow, case_id)
        if case is None:
            sys.exit(f"no case {case_id} in data/demo.db")
        amount = int(sys.argv[2]) if len(sys.argv) > 2 else case.amount_due_inr
    body = json.dumps(
        {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": f"pay_demo{int(time.time())}",
                        "amount": amount * 100,
                        "method": "upi",
                        "notes": {"case_id": str(case_id)},
                    }
                }
            },
        }
    ).encode()
    sig = hmac.new(os.environ["RAZORPAY_WEBHOOK_SECRET"].encode(), body, hashlib.sha256).hexdigest()
    r = requests.post(
        "http://localhost:8000/webhooks/razorpay",
        data=body,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
        timeout=10,
    )
    print(r.status_code, r.json())


if __name__ == "__main__":
    main()
