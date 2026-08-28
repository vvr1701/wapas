# Architecture

Wapas closes the full Track-3 loop: **detect → diagnose → choose → gate → execute → verify → measure.**
The one sentence that organizes everything: *every money action passes a deterministic
guardrails gate — the LLM never decides what's allowed* (see [PRD §6.1](PRD.md)).

```
                                ┌──────────────────────────────────────────┐
                                │       MERCHANT WORLD SIMULATOR           │
                                │  seed_razorpay.py → real test-mode objs  │
                                │  (customers, plan, subs, orders, invoices)│
                                │  event_generator.py → failure events     │
                                │  using Razorpay's real error taxonomy    │
                                │  + hidden customer behavior model (frozen│
                                │  after Phase 1; agent can never read it) │
                                └────────────────────┬─────────────────────┘
                                                     │ revenue-at-risk events
                                                     ▼
┌─────────────┐   poll/inject   ┌──────────────────────────────────────────┐
│ Razorpay    │◄───────────────►│  INGESTION & DETECTOR  (agent/detector)  │
│ test-mode   │  (Orders, Subs, │  normalize → open RecoveryCase           │
│ APIs        │  Invoices,      │  one case per entity (DB-enforced)       │
└─────────────┘  Payments)      └────────────────────┬─────────────────────┘
                                                     ▼
                                ┌──────────────────────────────────────────┐
                                │  DIAGNOSIS ENGINE  (agent/diagnosis)     │
                                │  deterministic error_reason → root cause │
                                │  (verified against live Razorpay docs);  │
                                │  unknown → UNKNOWN → escalate, never     │
                                │  guessed                                 │
                                └────────────────────┬─────────────────────┘
                                                     ▼
                                ┌──────────────────────────────────────────┐
                                │  POLICY ENGINE  (agent/policy)           │
                                │  playbooks in policies.yaml, content-    │
                                │  hashed; every PlannedAction carries     │
                                │  rule_id + rationale + policy hash       │
                                └────────────────────┬─────────────────────┘
                                                     ▼
                    ┌────────────────────────────────────────────────────────┐
                    │  GUARDRAILS GATE  (agent/guardrails) ← pass or die     │
                    │  terminal check · caps · cooldowns · 10:00–19:00 IST   │
                    │  window · opt-out registry · voice value threshold ·   │
                    │  incentive budget · idempotency key (at-most-once)     │
                    └───────┬───────────────────┬───────────────────┬────────┘
                            ▼                   ▼                   ▼
                  ┌──────────────┐    ┌──────────────────┐  ┌───────────────┐
                  │ NUDGES       │    │ HINGLISH VOICE   │  │ ESCALATION    │
                  │ (channels/   │    │ (channels/voice) │  │ (agent/       │
                  │ nudge, links)│    │ Sarvam STT → LLM │  │ escalation)   │
                  │ tone-linted, │    │ inside CODE rails│  │ self-sufficient│
                  │ real payable │    │ → Sarvam TTS +   │  │ context packets│
                  │ links        │    │ promise extract  │  └───────────────┘
                  └──────┬───────┘    └────────┬─────────┘
                         │                     │
                         ▼                     ▼
                ┌─────────────────────────────────────────┐
                │  PROMISE LEDGER  (ledger/promises)      │
                │  PENDING → KEPT | PARTIAL | BROKEN      │
                │  (+1 day grace; verified vs payments)   │
                └────────────────────┬────────────────────┘
                                     ▼
     ┌───────────────────────────────────────────────────────────────┐
     │  APPEND-ONLY AUDIT LOG  (ledger/audit) — hash-chained         │
     │  record_hash = SHA256(prev_hash + canonical_payload)          │
     │  no business write without a paired record (service layer)    │
     └────────────────────┬──────────────────────────────────────────┘
                          ▼
     ┌───────────────────────────────────────────────────────────────┐
     │  EVAL HARNESS  (evalh/) — 3 arms, one world, same seed        │
     │  do-nothing / baseline / agent → metrics.json + manifest      │
     └────────────────────┬──────────────────────────────────────────┘
                          ▼
     ┌───────────────────────────────────────────────────────────────┐
     │  DASHBOARD  (dashboard/) — 5 Streamlit screens; every number  │
     │  traces to a metrics.json key; timelines render from the      │
     │  audit log only                                               │
     └───────────────────────────────────────────────────────────────┘
```

## Case lifecycle state machine (the spine)

```
DETECTED → DIAGNOSED → PLANNED → GATED ──pass──→ EXECUTING → AWAITING_OUTCOME
                                   │                              │
                                   └─blocked→ (replan/STOPPED)    ├─→ RECOVERED (terminal ✓)
                                                                  ├─→ PROMISE_PENDING → RECOVERED
                                                                  │        └─ broken/partial → PLANNED
                                                                  ├─→ retry loop → PLANNED (until caps)
                                                                  ├─→ ESCALATED (terminal, human queue)
                                                                  ├─→ STOPPED (terminal: opt-out)
                                                                  └─→ EXHAUSTED (terminal, honest failure)
```

Transitions happen only along defined edges (`agent/cases.py`); terminal states are
immutable; **every** transition writes an audit record. `STOPPED` is reachable from any
non-terminal state — an opt-out halts a case instantly no matter where it is.

## Where the LLM earns its place (and where it is banned)

| Decision | Who decides |
|---|---|
| Is this action allowed? (caps, windows, opt-outs, budgets) | **Deterministic code only** |
| Root cause from an error code | Lookup table (`config/error_map.yaml`) |
| What to say on a call / in a nudge | Claude Sonnet 5, inside code rails (disclosure prepended by code; output tone- and authority-linted before speaking) |
| Promise extraction from a transcript | Claude Opus 5 → pydantic validation → deterministic rails (confidence/amount/date) → human review on anything shaky |
| When / which channel / what sequence | Policy engine rules (`config/policies.yaml`) |

Data model: [`schema.sql`](schema.sql) (generated from `ledger/db.py`).
