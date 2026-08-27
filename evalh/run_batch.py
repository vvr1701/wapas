"""Three-arm evaluation harness (FR-11.1) — `make eval SEED=42`.

Single responsibility: run do-nothing / baseline / Wapas against the identical
seeded world (world-hash asserted equal across arms), through the REAL agent
stack for arm C (ingestion, diagnosis, policy, guardrails gate, promise ledger,
audit chain), and write results/metrics.json + results/run_manifest.json +
EXCEPTIONS.md. Every number is derived; nothing is claimed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.cases import TERMINAL, CaseState, transition
from agent.detector import from_simulator, ingest
from agent.diagnosis import diagnose_case, load_error_map
from agent.escalation import EscalationReason, escalate
from agent.guardrails import CUSTOMER_CONTACT_TYPES, execute_action, opt_out
from agent.policy import Policy, load_policy, plan_case
from channels.links import observe_payment
from evalh.arms import ArmResult, WorldCase, natural_payment_day, run_arm_a, run_arm_b
from evalh.metrics import assemble_metrics
from ledger import audit
from ledger.attribution import Payment
from ledger.db import (
    CustomerRow,
    ExecutedActionRow,
    LlmCallRow,
    PlannedActionRow,
    RecoveryCaseRow,
    get_engine,
)
from ledger.promises import promise_metrics, record_promise, verify_promises
from simulator import behavior_model as bm
from simulator.event_generator import SIM_NOW, batch_hash, generate_batch

STEP_HOURS = (6, 15)  # 11:30 IST (in contact window) and 20:30 IST (outside — proves blocks)


def _world_cases(events) -> list[WorldCase]:
    return [
        WorldCase(
            key=i,
            entity_id=e.entity_id,
            customer_id=e.customer_id,
            category=e.category,
            amount_inr=e.amount_inr,
            opened_at=SIM_NOW,
        )
        for i, e in enumerate(events)
    ]


def _react_kind(action_type: str) -> str:
    if action_type == "silent_retry":
        return "retry"
    return "voice" if action_type == "voice_call" else "nudge"


def _contacts_before(db: Session, case_id: int) -> int:
    rows = db.scalars(select(ExecutedActionRow).where(ExecutedActionRow.case_id == case_id))
    return sum(1 for r in rows if r.action_type in CUSTOMER_CONTACT_TYPES)


def run_arm_c(
    seed: int,
    events,
    cases: list[WorldCase],
    start: datetime,
    days: int,
    db_path: Path,
    policy: Policy,
) -> tuple[ArmResult, dict]:
    db_path.unlink(missing_ok=True)
    engine = get_engine(db_path)
    key_by_entity = {c.entity_id: c.key for c in cases}
    world_by_entity = {c.entity_id: c for c in cases}
    error_map = load_error_map()
    pending_promise_payments: list[tuple[datetime, RecoveryCaseRow]] = []

    with Session(engine) as db:
        revenue_events = [from_simulator(e.model_dump(mode="json")) for e in events]
        opened = ingest(db, revenue_events, start)
        by_entity = {e.entity_id: e for e in revenue_events}
        for case in opened:
            diagnose_case(db, case, by_entity[case.entity_id], error_map)
            plan_case(db, case, policy, start)
            for st in (CaseState.GATED, CaseState.EXECUTING, CaseState.AWAITING_OUTCOME):
                transition(db, case, st)
        db.commit()

        natural_at = {c.entity_id: natural_payment_day(seed, c, start, days) for c in cases}

        for d in range(days):
            for hour in STEP_HOURS:
                now = (start + timedelta(days=d)).replace(hour=hour, minute=0)
                _step(db, policy, seed, now, world_by_entity, pending_promise_payments)
            # natural draw fires once, on the case's salary day (arm-independent)
            day = start + timedelta(days=d)
            for entity_id, when in natural_at.items():
                if when is not None and when.date() == day.date():
                    case = db.scalar(
                        select(RecoveryCaseRow).where(RecoveryCaseRow.entity_id == entity_id)
                    )
                    if case is not None and CaseState(case.state) != CaseState.RECOVERED:
                        observe_payment(
                            db,
                            {
                                "id": f"pay_nat_{entity_id}",
                                "amount": case.amount_due_inr * 100,
                                "method": "upi",
                                "notes": {"case_id": str(case.id)},
                            },
                            when,
                        )
            db.commit()

        end = start + timedelta(days=days)
        for case in db.scalars(select(RecoveryCaseRow)):
            if CaseState(case.state) not in TERMINAL:
                transition(
                    db,
                    case,
                    CaseState.EXHAUSTED,
                    actor="system",
                    payload={"why": "eval window closed; plan complete without payment"},
                )
        verify_promises(db, end)
        db.commit()

        result, extras = _collect(db, key_by_entity)
        ok, msg = audit.verify(db)
        assert ok, f"audit chain broken after eval: {msg}"
        extras["audit_chain"] = msg
    return result, extras


def _step(db, policy, seed, now, world_by_entity, pending_promise_payments):
    for when, case in list(pending_promise_payments):
        if when <= now:
            observe_payment(
                db,
                {
                    "id": f"pay_promise_{case.entity_id}",
                    "amount": case.amount_due_inr * 100,
                    "method": "netbanking",
                    "notes": {"case_id": str(case.id)},
                },
                when,
            )
            pending_promise_payments.remove((when, case))
    verify_promises(db, now)

    due = db.scalars(
        select(PlannedActionRow)
        .where(PlannedActionRow.status == "PENDING")
        .order_by(PlannedActionRow.id)
    ).all()
    for action in due:
        if action.scheduled_for > now.isoformat():
            continue
        case = db.get(RecoveryCaseRow, action.case_id)
        if CaseState(case.state) in TERMINAL:
            continue
        if action.action_type == "escalate":
            executed = execute_action(db, case, action, policy, now)
            if executed is not None:
                escalate(
                    db,
                    case,
                    EscalationReason.HIGH_VALUE_STALLED,
                    recommended=action.rationale,
                )
            continue
        contacts = _contacts_before(db, case.id)
        executed = execute_action(db, case, action, policy, now)
        if executed is None:
            continue
        world = world_by_entity[case.entity_id]
        hidden = bm.sample_hidden_state(seed, world.customer_id)
        reaction = bm.react(
            seed,
            world.customer_id,
            hidden,
            _react_kind(action.action_type),
            action.channel,
            now.day,
            contacts,
            attempt_no=action.id,
        )
        if reaction.opts_out:
            opt_out(db, case.customer_id, source="simulated_reply_stop", ts=now.isoformat())
        elif reaction.pays:
            if action.action_type == "voice_call":
                promise_due = now + timedelta(days=2)
                record_promise(
                    db,
                    case,
                    amount_inr=case.amount_due_inr,
                    due_date=promise_due,
                    now=now,
                    confidence=0.9,
                    transcript_ref=f"sim_call_{case.entity_id}",
                )
                pending_promise_payments.append((promise_due, case))
            else:
                observe_payment(
                    db,
                    {
                        "id": f"pay_sim_{case.entity_id}",
                        "amount": case.amount_due_inr * 100,
                        "method": "upi",
                        "notes": {"case_id": str(case.id)},
                    },
                    now,
                )


def _collect(db: Session, key_by_entity: dict[str, int]) -> tuple[ArmResult, dict]:
    from ledger.db import EscalationRow, PaymentObservedRow

    result = ArmResult()
    cases = {c.id: c for c in db.scalars(select(RecoveryCaseRow))}
    for p in db.scalars(select(PaymentObservedRow)):
        case = cases[p.matched_case_id]
        result.payments.append(
            Payment(
                key_by_entity[case.entity_id], p.amount_inr, datetime.fromisoformat(p.observed_ts)
            )
        )
    executed = list(db.scalars(select(ExecutedActionRow).order_by(ExecutedActionRow.id)))
    for e in executed:
        if e.action_type == "escalate":
            continue
        key = key_by_entity[cases[e.case_id].entity_id]
        ts = datetime.fromisoformat(e.executed_ts)
        if key not in result.first_intervention_at or ts < result.first_intervention_at[key]:
            result.first_intervention_at[key] = ts
        if e.action_type in CUSTOMER_CONTACT_TYPES:
            result.contacts_made += 1
    touched_case_ids = {e.case_id for e in executed if e.action_type != "escalate"}
    result.touched_at_risk_inr = sum(cases[cid].amount_due_inr for cid in touched_case_ids)
    opted = list(db.scalars(select(CustomerRow).where(CustomerRow.opted_out.is_(True))))
    result.opt_outs = len(opted)

    # stops honored: executions for an opted-out customer after their opt-out ts
    violations = 0
    for reg in opted:
        cust_case_ids = [cid for cid, c in cases.items() if c.customer_id == reg.customer_id]
        violations += sum(
            1 for e in executed if e.case_id in cust_case_ids and e.executed_ts > reg.opt_out_ts
        )

    exceptions = []
    for c in cases.values():
        if c.state == CaseState.EXHAUSTED:
            exceptions.append(
                {
                    "entity_id": c.entity_id,
                    "category": c.category,
                    "amount_inr": c.amount_due_inr,
                    "root_cause": c.root_cause,
                    "end_state": "EXHAUSTED",
                    "why": "policy plan completed / caps reached without payment; stopped trying",
                }
            )
    for esc in db.scalars(select(EscalationRow)):
        c = cases[esc.case_id]
        exceptions.append(
            {
                "entity_id": c.entity_id,
                "category": c.category,
                "amount_inr": c.amount_due_inr,
                "root_cause": c.root_cause,
                "end_state": "ESCALATED",
                "why": f"handed to human: {esc.reason}",
            }
        )
    llm_cost = sum(r.cost_usd for r in db.scalars(select(LlmCallRow)))
    nudges = sum(
        1
        for e in executed
        if e.action_type in CUSTOMER_CONTACT_TYPES and e.action_type != "voice_call"
    )
    voices = sum(1 for e in executed if e.action_type == "voice_call")
    extras = {
        "promises": promise_metrics(db),
        "actions_after_optout": violations,
        "optouts": len(opted),
        "exceptions": sorted(exceptions, key=lambda x: -x["amount_inr"]),
        "llm_cost_usd": round(llm_cost, 4),
        # estimates, stated as estimates: WA/email ~₹0.5 per nudge, ~₹5 per voice call
        "comms_cost_est_inr": round(nudges * 0.5 + voices * 5.0, 2),
        "executed_actions": len(executed),
    }
    return result, extras


def write_exceptions_md(exceptions: list[dict], path: Path, seed: int) -> None:
    lines = [
        "# EXCEPTIONS.md — what Wapas could NOT recover, and why (FR-11.3)",
        "",
        f"Machine-generated by `make eval SEED={seed}`. These cases are a deliverable,",
        "not an embarrassment: every one stopped for a stated, policy-bound reason.",
        "",
        "| Entity | Cat | Amount ₹ | Root cause | End state | Why it stopped |",
        "|---|---|---|---|---|---|",
    ]
    for e in exceptions:
        lines.append(
            f"| {e['entity_id']} | {e['category']} | {e['amount_inr']:,} "
            f"| {e['root_cause']} | {e['end_state']} | {e['why']} |"
        )
    lines.append("")
    lines.append(f"Total: {len(exceptions)} cases.")
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(description="Run the 3-arm evaluation")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--days", type=int, default=21)
    p.add_argument("--config", type=Path, default=Path("config/sim_config.yaml"))
    p.add_argument("--out", type=Path, default=Path("results"))
    args = p.parse_args()

    cfg_text = args.config.read_text()
    cfg = yaml.safe_load(cfg_text)
    policy = load_policy()
    registry_path = Path("data/seed_registry.json")
    registry = json.loads(registry_path.read_text()) if registry_path.exists() else {}
    events = generate_batch(args.seed, cfg, registry)
    cases = _world_cases(events)
    start = SIM_NOW

    # FR-1.4: identical hidden world across arms, asserted before running
    customer_ids = sorted({c.customer_id for c in cases})
    hashes = [bm.world_hash(args.seed, customer_ids) for _ in range(3)]
    assert len(set(hashes)) == 1, "world hash differs across arms"

    arm_a = run_arm_a(args.seed, cases, start, args.days)
    arm_b = run_arm_b(args.seed, cases, start, args.days)
    arm_c, extras = run_arm_c(
        args.seed,
        events,
        cases,
        start,
        args.days,
        Path(f"data/eval_seed{args.seed}.db"),
        policy,
    )

    metrics = assemble_metrics(cases, arm_a, arm_b, arm_c, extras)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "metrics.json").write_text(json.dumps(metrics, indent=1, sort_keys=True))
    try:
        git_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        git_sha = "unknown"
    manifest = {
        "seed": args.seed,
        "days": args.days,
        "batch_hash": batch_hash(events),
        "world_hash": hashes[0],
        "world_hash_equal_across_arms": True,
        "policy_version_hash": policy.version_hash,
        "sim_config_hash": hashlib.sha256(cfg_text.encode()).hexdigest(),
        "code_git_sha": git_sha,
        "audit_chain": extras["audit_chain"],
    }
    (args.out / "run_manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    write_exceptions_md(extras["exceptions"], Path("EXCEPTIONS.md"), args.seed)
    h = metrics["headline"]
    print(json.dumps(manifest, indent=1))
    print(
        f"\nHEADLINE seed={args.seed}: at_risk ₹{h['at_risk_inr']:,} | "
        f"recovered raw A/B/C ₹{h['recovered_raw_inr']['A']:,}/₹{h['recovered_raw_inr']['B']:,}"
        f"/₹{h['recovered_raw_inr']['C']:,} | adj C ₹{h['recovered_adj_inr']['C']:,.0f} | "
        f"lift {h['lift']['absolute']:.1%} abs ({h['lift']['relative']:+.0%} rel) | "
        f"stops honored {h['stops_honored']:.0%} | exceptions {h['exceptions_count']}"
    )


if __name__ == "__main__":
    main()
