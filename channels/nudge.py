"""Nudge channel (FR-6.1): render Hinglish-flavored, dignity-first messages and
deliver them to a local outbox (simulated delivery, clearly labeled).

Single responsibility: deterministic template rendering + tone lint. Amount,
link, and dates are template variables — never model-generated (PRD §6.1).
LLM personalization within tone guidelines is a P1 add-on behind the same
render() interface; the templates below are the P0 deliverable.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

OUTBOX_DIR = Path("data/outbox")

FOOTER = "automated message from Kirana+ · reply STOP to opt out"

# Dignity lint (C-5): customer-facing copy must never contain these.
BANNED_PHRASES = [
    "legal action",
    "legal notice",
    "court",
    "police",
    "lawyer",
    "consequences",
    "or else",
    "blacklist",
    "defaulter",
    "shame",
    "warning",
    "final notice",
    "last chance",
    "penalty",
    "arrest",
    "kanooni",
    "adalat",
    "warna",
    "anjaam",
]


class NudgeContext(BaseModel):
    """Everything a template may reference. All facts, no free text."""

    case_id: int
    action_type: str
    category: str  # L1 | L2 | L3
    channel: str  # email | whatsapp
    customer_name: str
    amount_inr: int
    payment_link_url: str | None = None
    due_date: str | None = None
    invoice_no: str | None = None
    language: str = "hi-IN"  # template pack; unknown packs fall back to hi-IN


# Keyed by (action_type, category). Subject used only for email. Customer copy
# is a *policy artifact*: one reviewed, tone-linted, golden-tested pack per
# language — the LLM never writes it. Adding a language = adding a pack here.
_TEMPLATES: dict[tuple[str, str], dict[str, str]] = {
    ("link_nudge", "L1"): {
        "subject": "Kirana+ subscription — payment link",
        "body": (
            "Namaste {customer_name} ji,\n\n"
            "Aapke Kirana+ subscription (₹{amount}) ka renewal is baar process nahi ho paya. "
            "Koi baat nahi — jab aapko convenient ho, is secure link se payment complete "
            "kar sakte hain:\n{link}\n\n"
            "Koi sawaal ho toh bas reply kariye, hum madad karenge.\n"
        ),
    },
    ("link_nudge", "L2"): {
        "subject": "Aapka Kirana+ order aapka intezaar kar raha hai",
        "body": (
            "Namaste {customer_name} ji,\n\n"
            "Aapka Kirana+ order (₹{amount}) bas ek step door hai. Payment yahan "
            "complete kar sakte hain:\n{link}\n\n"
            "Agar checkout mein koi dikkat aayi thi, reply kariye — hum turant help karenge.\n"
        ),
    },
    ("method_update_nudge", "L1"): {
        "subject": "Kirana+ subscription — payment method update kariye",
        "body": (
            "Namaste {customer_name} ji,\n\n"
            "Aapke Kirana+ subscription (₹{amount}/month) ka payment method ab kaam nahi "
            "kar raha (card expire ho gaya lagta hai). Naya method update karne ke liye, ya "
            "is baar direct pay karne ke liye, yeh link use kariye:\n{link}\n\n"
            "Do minute ka kaam hai. Koi help chahiye toh reply kariye.\n"
        ),
    },
    ("email_nudge", "L3"): {
        "subject": "Gentle reminder: invoice {invoice_no} (₹{amount})",
        "body": (
            "Namaste {customer_name} ji,\n\n"
            "Ek gentle reminder — invoice {invoice_no} (₹{amount}), due date {due_date}, "
            "abhi pending hai. Ho sakta hai busy schedule mein miss ho gaya ho, isliye "
            "payment link saath bhej rahe hain:\n{link}\n\n"
            "Agar payment already ho chuki hai ya koi query hai, please reply kariye — "
            "hum records check kar lenge.\n"
        ),
    },
    ("wa_nudge", "L3"): {
        "subject": "",
        "body": (
            "Namaste {customer_name} ji! Invoice {invoice_no} (₹{amount}, due {due_date}) "
            "ka payment abhi pending hai. Jab convenient ho, yahan se pay kar sakte "
            "hain: {link}\nAlready paid? Bas reply kar dijiye, hum check kar lenge.\n"
        ),
    },
    ("link_nudge", "L3"): {
        "subject": "Invoice {invoice_no} — payment link",
        "body": (
            "Namaste {customer_name} ji,\n\n"
            "Invoice {invoice_no} (₹{amount}) ke liye payment link:\n{link}\n\n"
            "Koi query ho toh reply kariye.\n"
        ),
    },
}


_TEMPLATES_EN: dict[tuple[str, str], dict[str, str]] = {
    ("link_nudge", "L1"): {
        "subject": "Kirana+ subscription — payment link",
        "body": (
            "Hello {customer_name},\n\n"
            "The renewal for your Kirana+ subscription (₹{amount}) could not be processed "
            "this time. No trouble at all — whenever it is convenient, you can complete "
            "the payment through this secure link:\n{link}\n\n"
            "If you have any questions, just reply and we will help.\n"
        ),
    },
    ("link_nudge", "L2"): {
        "subject": "Your Kirana+ order is waiting for you",
        "body": (
            "Hello {customer_name},\n\n"
            "Your Kirana+ order (₹{amount}) is one step away. You can complete the "
            "payment here:\n{link}\n\n"
            "If something went wrong at checkout, reply and we will sort it out right away.\n"
        ),
    },
    ("method_update_nudge", "L1"): {
        "subject": "Kirana+ subscription — please update your payment method",
        "body": (
            "Hello {customer_name},\n\n"
            "The payment method on your Kirana+ subscription (₹{amount}/month) is no "
            "longer working (the card looks expired). You can update it, or pay directly "
            "this time, using this link:\n{link}\n\n"
            "It takes two minutes. Reply if you need any help.\n"
        ),
    },
    ("email_nudge", "L3"): {
        "subject": "Gentle reminder: invoice {invoice_no} (₹{amount})",
        "body": (
            "Hello {customer_name},\n\n"
            "A gentle reminder — invoice {invoice_no} (₹{amount}), due {due_date}, is "
            "still pending. It may simply have slipped through a busy schedule, so here "
            "is the payment link:\n{link}\n\n"
            "If it is already paid, or you have any query, please reply — we will check "
            "our records.\n"
        ),
    },
    ("wa_nudge", "L3"): {
        "subject": "",
        "body": (
            "Hello {customer_name}! Invoice {invoice_no} (₹{amount}, due {due_date}) is "
            "still pending. Whenever convenient, you can pay here: {link}\n"
            "Already paid? Just reply and we will check.\n"
        ),
    },
    ("link_nudge", "L3"): {
        "subject": "Invoice {invoice_no} — payment link",
        "body": (
            "Hello {customer_name},\n\n"
            "Payment link for invoice {invoice_no} (₹{amount}):\n{link}\n\n"
            "Reply if you have any query.\n"
        ),
    },
}

# Extra language packs; hi-IN (_TEMPLATES) is the default and the fallback.
_PACKS: dict[str, dict[tuple[str, str], dict[str, str]]] = {"en-IN": _TEMPLATES_EN}


def tone_lint(text: str) -> list[str]:
    """Return every banned phrase found (empty list == clean)."""
    low = text.lower()
    return [p for p in BANNED_PHRASES if p in low]


def render(ctx: NudgeContext) -> dict[str, str]:
    """Deterministic render. Raises on unknown template or tone violation —
    a nudge that can't pass its own lint never leaves the building."""
    pack = _PACKS.get(ctx.language, _TEMPLATES)
    tpl = pack.get((ctx.action_type, ctx.category)) or _TEMPLATES[(ctx.action_type, ctx.category)]
    fields = {
        "customer_name": ctx.customer_name,
        "amount": f"{ctx.amount_inr:,}",
        "link": ctx.payment_link_url or "(link unavailable)",
        "due_date": ctx.due_date or "",
        "invoice_no": ctx.invoice_no or "",
    }
    body = tpl["body"].format(**fields) + "\n— " + FOOTER
    subject = tpl["subject"].format(**fields)
    violations = tone_lint(subject + "\n" + body)
    if violations:
        raise ValueError(f"tone lint failed: {violations}")
    return {"subject": subject, "body": body}


def write_outbox(
    ctx: NudgeContext, rendered: dict[str, str], ts: str, outdir: Path = OUTBOX_DIR
) -> Path:
    """Simulated delivery: one file per message, honestly labeled (SIMULATION.md)."""
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"case{ctx.case_id}_{ctx.action_type}_{ctx.channel}_{ts}.txt"
    header = (
        "=== SIMULATED DELIVERY — no real message was sent ===\n"
        f"To: {ctx.customer_name} via {ctx.channel}\n"
        f"Case: {ctx.case_id}\n"
        + (f"Subject: {rendered['subject']}\n" if ctx.channel == "email" else "")
        + "\n"
    )
    path.write_text(header + rendered["body"])
    return path
