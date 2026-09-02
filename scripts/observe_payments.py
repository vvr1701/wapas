"""Poll Razorpay test-mode payments and feed any carrying notes.case_id through
observe_payment against the demo DB. Run after paying a demo payment link:

    uv run python -m scripts.observe_payments
"""

import os
from datetime import UTC, datetime
from pathlib import Path

import razorpay
from sqlalchemy.orm import Session

from channels.links import observe_payment
from ledger.db import get_engine


def main() -> None:
    client = razorpay.Client(
        auth=(os.environ["RAZORPAY_KEY_ID"], os.environ["RAZORPAY_KEY_SECRET"])
    )
    payments = client.payment.all({"count": 25})["items"]
    with Session(get_engine(Path("data/demo.db"))) as db:
        seen = 0
        for pay in payments:
            if pay.get("status") != "captured":
                continue
            if not (pay.get("notes") or {}).get("case_id"):
                continue
            if observe_payment(db, pay, datetime.now(UTC)):
                seen += 1
        db.commit()
    print(f"observed {seen} new payment(s)")


if __name__ == "__main__":
    main()
