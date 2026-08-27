"""Hidden customer behavior model (FR-1.3, FR-1.4).

Single responsibility: sample per-customer hidden state and decide, probabilistically
and deterministically per seed, how a customer reacts to an intervention or pays
naturally. FROZEN OUTSIDE PHASE 1 — modifying this file to improve eval numbers is
gaming and disqualifying by design. The agent must never import this module
(enforced by tests/test_import_guard.py); it observes outcomes only.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

SALARY_DAYS = (1, 7, 15)
CHANNELS = ("email", "whatsapp", "voice")


@dataclass(frozen=True)
class HiddenState:
    """Per-customer latent state, sampled once at world-creation time."""

    liquidity_day: int  # day of month cash is most available
    channel_responsiveness: dict[str, float]  # channel -> [0, 1]
    willingness_to_pay: float  # [0, 1]
    annoyance_threshold: int  # contacts tolerated before disengaging
    opt_out_propensity: float  # [0, 1]


@dataclass(frozen=True)
class Reaction:
    """Observable outcome of one interaction. This is ALL the agent may see."""

    pays: bool
    opts_out: bool
    disengaged: bool


def _rng(seed: int, *parts: object) -> random.Random:
    """Deterministic RNG derived from seed + a stable key. No global state."""
    key = hashlib.sha256(f"{seed}|{'|'.join(map(str, parts))}".encode()).hexdigest()
    return random.Random(int(key, 16))


def sample_hidden_state(seed: int, customer_id: str) -> HiddenState:
    """Sample a customer's hidden state. Same (seed, customer_id) -> same state."""
    r = _rng(seed, "hidden", customer_id)
    return HiddenState(
        liquidity_day=r.choice(SALARY_DAYS),
        channel_responsiveness={c: round(r.uniform(0.1, 0.9), 3) for c in CHANNELS},
        willingness_to_pay=round(r.betavariate(2.5, 1.5), 3),
        annoyance_threshold=r.randint(2, 5),
        opt_out_propensity=round(r.betavariate(1.2, 6.0), 3),
    )


def world_hash(seed: int, customer_ids: list[str]) -> str:
    """Content hash of the entire hidden world. The eval harness asserts this is
    identical across all three arms before running (FR-1.4)."""
    h = hashlib.sha256()
    for cid in sorted(customer_ids):
        h.update(f"{cid}:{sample_hidden_state(seed, cid)}".encode())
    return h.hexdigest()


def _timing_fit(hidden: HiddenState, day_of_month: int) -> float:
    """Cash-availability multiplier: strong near the customer's liquidity day."""
    raw = abs(day_of_month - hidden.liquidity_day)
    dist = min(raw, 31 - raw)
    return 1.0 if dist <= 2 else (0.6 if dist <= 5 else 0.3)


def react(
    seed: int,
    customer_id: str,
    hidden: HiddenState,
    kind: str,  # "retry" (silent) | "nudge" | "voice"
    channel: str,  # "bank" | "email" | "whatsapp" | "voice"
    day_of_month: int,
    contacts_so_far: int,
    attempt_no: int,
) -> Reaction:
    """One interaction -> one deterministic-per-seed probabilistic reaction.

    Success depends only on hidden state, intervention fit, and timing — so an
    agent wins by better timing/channel/sequencing, never by simulator access.
    """
    r = _rng(seed, "react", customer_id, kind, channel, attempt_no)
    if kind == "retry":  # silent bank retry: no annoyance, timing-dominated
        p = hidden.willingness_to_pay * _timing_fit(hidden, day_of_month) * 0.9
        return Reaction(pays=r.random() < p, opts_out=False, disengaged=False)
    if contacts_so_far >= hidden.annoyance_threshold:
        opts_out = r.random() < hidden.opt_out_propensity
        return Reaction(pays=False, opts_out=opts_out, disengaged=True)
    opts_out = r.random() < hidden.opt_out_propensity * 0.1
    if opts_out:
        return Reaction(pays=False, opts_out=True, disengaged=True)
    resp = hidden.channel_responsiveness.get(channel, 0.2)
    p = hidden.willingness_to_pay * resp * _timing_fit(hidden, day_of_month)
    if kind == "voice":  # a live call converts better than a message, at annoyance cost
        p = min(1.0, p * 1.5)
    return Reaction(pays=r.random() < p, opts_out=False, disengaged=False)


def pays_naturally(seed: int, customer_id: str, hidden: HiddenState, day_of_month: int) -> bool:
    """Arm-A behavior: some customers pay with no intervention at all (FR-11.1).
    Claiming credit for these is the dishonesty the eval harness corrects for."""
    r = _rng(seed, "natural", customer_id, day_of_month)
    return r.random() < hidden.willingness_to_pay * 0.15 * _timing_fit(hidden, day_of_month)
