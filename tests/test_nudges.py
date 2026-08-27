"""FR-6.1 exit-gate tests: 6 golden-file renders, banned-phrase tone lint,
outbox labeling."""

from pathlib import Path

import pytest

from channels.nudge import BANNED_PHRASES, FOOTER, NudgeContext, render, tone_lint, write_outbox

GOLDEN_DIR = Path(__file__).parent / "golden"

CONTEXTS = [
    NudgeContext(
        case_id=1,
        action_type="link_nudge",
        category="L1",
        channel="whatsapp",
        customer_name="Meera Iyer",
        amount_inr=499,
        payment_link_url="https://rzp.io/l/test1",
    ),
    NudgeContext(
        case_id=2,
        action_type="link_nudge",
        category="L2",
        channel="whatsapp",
        customer_name="Rohan Das",
        amount_inr=2350,
        payment_link_url="https://rzp.io/l/test2",
    ),
    NudgeContext(
        case_id=3,
        action_type="link_nudge",
        category="L2",
        channel="email",
        customer_name="Sana Khan",
        amount_inr=4100,
        payment_link_url="https://rzp.io/l/test3",
    ),
    NudgeContext(
        case_id=4,
        action_type="method_update_nudge",
        category="L1",
        channel="email",
        customer_name="Kabir Mehta",
        amount_inr=499,
        payment_link_url="https://rzp.io/l/test4",
    ),
    NudgeContext(
        case_id=5,
        action_type="email_nudge",
        category="L3",
        channel="email",
        customer_name="Anjali Nair",
        amount_inr=18000,
        payment_link_url="https://rzp.io/l/test5",
        due_date="2026-08-17",
        invoice_no="INV-0042",
    ),
    NudgeContext(
        case_id=6,
        action_type="wa_nudge",
        category="L3",
        channel="whatsapp",
        customer_name="Vikram Singh",
        amount_inr=52000,
        payment_link_url="https://rzp.io/l/test6",
        due_date="2026-08-20",
        invoice_no="INV-0017",
    ),
]


def _golden_path(ctx: NudgeContext) -> Path:
    return GOLDEN_DIR / f"{ctx.action_type}_{ctx.category}_{ctx.channel}.txt"


@pytest.mark.parametrize("ctx", CONTEXTS, ids=lambda c: f"{c.action_type}_{c.category}_{c.channel}")
def test_golden_render(ctx):
    rendered = render(ctx)
    text = f"SUBJECT: {rendered['subject']}\n---\n{rendered['body']}"
    golden = _golden_path(ctx)
    assert golden.exists(), f"golden file missing: {golden} — review and commit it"
    assert text == golden.read_text(), f"render drifted from golden {golden.name}"


@pytest.mark.parametrize("ctx", CONTEXTS, ids=lambda c: f"{c.action_type}_{c.category}_{c.channel}")
def test_every_nudge_passes_tone_lint_and_carries_optout_footer(ctx):
    rendered = render(ctx)
    assert tone_lint(rendered["subject"] + rendered["body"]) == []
    assert FOOTER in rendered["body"]  # C-3: disclosure + opt-out on every message
    # money facts are template variables, present verbatim:
    assert f"{ctx.amount_inr:,}" in rendered["body"]
    assert ctx.payment_link_url in rendered["body"]


def test_tone_lint_catches_banned_phrases():
    assert tone_lint("Pay now or we take LEGAL ACTION") == ["legal action"]
    assert set(tone_lint("final notice: court, police, warna...")) >= {"court", "police", "warna"}
    assert tone_lint("polite gentle reminder") == []
    assert len(BANNED_PHRASES) >= 15


def test_render_refuses_tone_violation():
    from channels import nudge

    bad = {
        ("link_nudge", "L1"): {
            "subject": "Final notice",
            "body": "pay or else {link}{amount}{customer_name}{due_date}{invoice_no}",
        }
    }
    original = nudge._TEMPLATES
    nudge._TEMPLATES = original | bad
    try:
        with pytest.raises(ValueError, match="tone lint"):
            render(CONTEXTS[0])
    finally:
        nudge._TEMPLATES = original


def test_outbox_labeled_simulated(tmp_path):
    ctx = CONTEXTS[4]
    path = write_outbox(ctx, render(ctx), ts="20260827T120000", outdir=tmp_path)
    content = path.read_text()
    assert "SIMULATED DELIVERY" in content
    assert "Subject:" in content  # email carries subject header
