"""Webhook receiver (FR-2.3) — the production-shaped ingestion path.

Single responsibility: accept Razorpay webhooks behind the ENABLE_WEBHOOKS
flag, verify the HMAC-SHA256 signature (X-Razorpay-Signature over the raw
body), and normalize payment events into the same pipeline polling feeds.
Demo-day ingestion stays polling + injection (no public URL needed); this
route exists because the production answer should too. README §10.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy.orm import Session

from channels.links import observe_payment
from ledger.db import get_engine

router = APIRouter()


def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request, x_razorpay_signature: str = Header(default="")
) -> dict:
    if os.getenv("ENABLE_WEBHOOKS", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="webhooks disabled")
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    body = await request.body()
    if not secret or not verify_signature(body, x_razorpay_signature, secret):
        raise HTTPException(status_code=401, detail="bad signature")
    event = json.loads(body)
    if event.get("event") == "payment.captured":
        payment = event["payload"]["payment"]["entity"]
        with Session(get_engine()) as db:
            observe_payment(db, payment, datetime.now(UTC))
            db.commit()
        return {"handled": "payment.captured"}
    return {"handled": "ignored", "event": event.get("event")}
