# BUILD_LOG

Daily: Shipped / Broke / Fixed / Decided (+why) / Next.

## Aug 27, 2026 — Phase 0: Scaffold & CI
- **Shipped:** repo structure per PRD §11.1, pyproject + uv.lock (py3.12), Makefile (test/lint live; seed/eval/dashboard/verify-audit stubbed to fail loudly), .env.example, CI (ruff lint+format+pytest), detect-secrets pre-commit + clean baseline, placeholder test.
- **Broke:** nothing.
- **Fixed:** n/a.
- **Decided:** uv over pip-tools (already installed, manages py3.12 itself on a py3.14 host). Runtime deps deferred to the phase that needs them — lockfile churn beats speculative pins.
- **Next:** Phase 1 — Merchant world (FR-1.1–1.4, 1.6). Needs Razorpay test-mode keys in .env.

## Aug 27, 2026 — Phase 1: Merchant world
- **Shipped:** hidden behavior model (liquidity day / channel responsiveness / willingness / annoyance / opt-out propensity; deterministic per seed, world_hash for FR-1.4), seeded event generator (250 events, L1/L2/L3, Appendix-A error taxonomy, batch_hash proof), idempotent crash-safe Razorpay seeder with local registry, sim_config.yaml, SIMULATION.md, 9 tests incl. import-guard.
- **Broke:** nothing.
- **Fixed:** n/a.
- **Decided:** generator falls back to sim_-prefixed entity ids when the world isn't seeded yet — keeps determinism tests offline; disclosed in SIMULATION.md. Seeder tested via fake client (zero creates on re-run) since no test keys are present yet.
- **BLOCKER (partial):** no Razorpay test keys in .env → live `make seed` unverified (idempotency logic proven against fake client only). Options: (a) add keys and run `make seed` twice before Phase 2 — preferred; (b) proceed to Phase 2 (needs no live objects) and verify seed before Phase 5's real payment-link loop.
- **Next:** Phase 2 — case spine: ingestion, state machine, hash-chained audit log.

## Aug 27, 2026 — Phase 1 addendum: live seed against real test-mode APIs
- **Shipped:** live world seeded — 250 customers, 80 orders, 50 invoices as real test-mode objects; `make seed` run twice → identical registry sha256 (6c8e855e…) — idempotency gate closed live.
- **Broke:** (1) Plans/Subscriptions API → Unauthorized (product not active on account, still, after dashboard enablement — likely propagation or partial activation); (2) rate limit "Too many requests" mid-seed; (3) hard test-mode cap: 30 payment links total.
- **Fixed:** (2) exponential backoff in Seeder._ensure (all creates route through it); (3) L2 entities seeded as Orders — truer to FR-2.2 anyway — and all 30 created links cancelled to reserve the budget for per-nudge links (FR-6.2); seeder sections isolated so a gated product can't block the rest.
- **Decided:** subscriptions stay as disclosed sim_ ids until the API unlocks; re-running `make seed` fills the gap with zero duplicates by design.
- **Next:** Phase 2 — case spine. Re-check /v1/plans before Phase 5.

## Aug 27, 2026 — Phase 2: Case spine
- **Shipped:** SQLAlchemy schema (revenue_events, recovery_cases, audit_log), hash-chained append-only audit log + `make verify-audit`, §4.2 state machine with edge enforcement + terminal immutability, FR-10.2 service layer (open_case/transition pair every business write with an audit record), normalizers for simulator/Razorpay payloads producing one RevenueEvent shape, detection rules with duplicate-case guard (service + DB unique constraint). 13 new tests incl. tamper/delete/rehash detection.
- **Broke:** nothing.
- **Fixed:** n/a.
- **Decided:** audit timestamps stored as ISO strings, canonical hash built from stored strings only — kills the tz/type round-trip class of verification bugs. STOPPED reachable from every non-terminal state (FR-5.2 needs instant halt; §4.2 diagram shows it from GATED/AWAITING_OUTCOME, generalized deliberately).
- **Next:** Phase 3 — diagnosis (rules-first) + policy engine + policies.yaml. Verify Razorpay error taxonomy against current docs (Appendix A note).

## Aug 27, 2026 — Phase 3: Diagnosis + policy engine
- **Shipped:** closed RootCause taxonomy + table-driven deterministic diagnosis (config/error_map.yaml; unmapped → UNKNOWN, never guessed), policy engine loading content-hashed policies.yaml with structured playbooks (timing DSL: +Nh/liquidity_window/due+Nd; value + voice-eligibility guards), PlannedAction persistence with rule_id + rationale + policy_version_hash on every row and per-action audit records. 24 new tests.
- **Broke:** nothing.
- **Fixed:** n/a.
- **Decided:** (1) Verified Razorpay card error_reason strings against live docs (razorpay.com/docs/errors/payments/cards/) — updated simulator taxonomy from starter map to documented values (insufficient_funds, card_expired, gateway_technical_error…); mandate reasons keep the starter map, noted. Batch hash for seed 42 changed accordingly (now 80e6028d…). (2) Appendix B's string DSL ("retry@liquidity_window") became structured YAML entries — same expressiveness, no parser to maintain. (3) Unknown (category × cause) pairs fall back to UNKNOWN playbook → escalate.
- **Next:** Phase 4 — guardrails gate, TESTS FIRST. Mandatory human diff review after it per §13.1.

## Aug 27, 2026 — Phase 4: Guardrails gate (tests first)
- **Shipped:** tests/test_guardrails.py written BEFORE the code (28 tests, red first), then agent/guardrails.py: ordered FR-5.1 checks (terminal, per-kind caps, cooldowns, IST contact window w/ silent-action exemption, opt-out registry, voice value threshold, incentive bounding incl. batch budget + per-case cap + allowed-cause + once-only, idempotency), FR-5.2 opt-out (instant, permanent, first-trigger-wins, cancels queued actions, stops all cases, fully audited), FR-5.3 blocked-with-reason + auto-replan to next window open. Schema: customers (opt-out registry) + executed_actions (unique idempotency_key). Coverage 98% (gate ≥95%).
- **Broke:** double-fire test failed on first implementation — replay was re-gated and blocked by nudge cooldown before the idempotency lookup.
- **Fixed:** replay of an already-executed planned action returns the existing execution row BEFORE re-gating (lookup by planned_id) — true at-most-once crash-retry semantics.
- **Decided:** at-most-once over at-least-once for crashed executions — for money-adjacent actions a lost retry beats a duplicate contact. Stop-intent rules are word-bounded regexes ("stopped by the shop" doesn't trip; "\bstop\b(?!ped)" does).
- **Next:** Phase 5 — channels + real payment-link money loop. MANDATORY human diff review of Phase 4 before starting (PRD §13.1).
