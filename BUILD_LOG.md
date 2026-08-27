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

## Aug 27, 2026 — Phase 5: Channels + real money loop
- **Shipped:** Hinglish nudge templates (6 goldens committed: link/method-update/invoice reminders across email+WhatsApp), tone lint with 19 banned phrases enforced at render time (a nudge that fails its own lint raises), simulated-delivery outbox with honest labeling, opt-out footer on every message, payments_observed table, invoice-backed payment links with notes-based case matching, observe_payment → RECOVERED with recovered-₹ accounting. Live e2e green: real link created → payment observed → case RECOVERED → ₹1,200 counted → re-observe idempotent.
- **Broke:** payment_link.create failed — test mode's 30-link cap is LIFETIME, not active-count; cancelling doesn't refund it (verified via probe). Our seeding collision had burned all 30.
- **Fixed:** per-nudge links are invoice-backed (Invoices API, uncapped, same payable short_url + hosted page + notes propagation). Disclosed in SIMULATION.md.
- **Decided:** LLM personalization of nudges deferred (P1) — deterministic templates ship the P0; money fields are template variables per §6.1 regardless. E2E test skips (never fakes green) without keys, so CI stays honest; gate run is local.
- **Next:** Phase 6 — promise ledger, attribution, escalation packets. L1+L3 happy-path e2e checkpoint.

## Aug 27, 2026 — Phase 6: Promises, attribution, escalation
- **Shipped:** promise ledger (KEPT/BROKEN/PARTIAL, +1d grace, kept → RECOVERED w/ voice_promise attribution, partial reduces amount_due + replans, broken replans a gentle follow-up), Appendix C attribution as pure functions (post-intervention-only credit, natural-rate adjustment, lift abs+rel, cost/₹, stops_honored), escalation reasons enum + self-sufficient context packets (summary/diagnosis/actions/timeline-from-audit/transcripts/next step) + human ack logging. Checkpoint green: L1 (insufficient_funds → liquidity retry → payment → RECOVERED) and L3 (invoice → reminder → voice promise → verified payment → KEPT → RECOVERED) e2e, both audit-chain-verified end to end.
- **Broke:** context packet had no transcripts — promise_recorded audit payload omitted transcript_ref.
- **Fixed:** transcript_ref added to the audit payload (packet reads transcripts from the audit log, the one source of truth).
- **Decided:** observe_payment only closes a case when payment ≥ amount_due — partials are recorded but never fake-RECOVER; the promise verifier owns partial semantics.
- **Next:** Phase 7 — Hinglish voice agent (conversation policy, text-mode harness, adversarial six, promise-extraction golden set). Needs ANTHROPIC_API_KEY for live LLM; text-harness tests must run without it in CI.

## Aug 27, 2026 — Phase 7: Hinglish voice agent
- **Shipped:** conversation policy as deterministic rails around the LLM (disclosure prepended by code, stop/dispute/abuse rule-classified, negotiation bounds ≤14d/≥50% in code, LLM output tone+discount-validated before speaking, fallback line on any model failure), call agent wiring rails to real state (in-call opt-out, DISPUTE/ABUSE_DISTRESS escalation, suspicious-input audit flags), promise extraction (Opus 5, strict JSON, 1 retry, rails: confidence/amount/date) with 20-transcript hand-labeled golden set, reply processing (stop/dispute/injection-as-content), Sarvam stt_tts.py (Saarika v2.5 / Bulbul v2, one-file swap point), FastAPI call console with mic capture + mid-session audio/text toggle + graceful degradation, llm_calls cost logging (Sonnet 5 converse / Opus 5 extract / Haiku 4.5 classify). Tests: FR-7.2 behaviors ×9, adversarial six, extraction rails, console flow — all CI-safe with zero keys.
- **Broke:** (1) anthropic SDK 1.x removed sampling params — `temperature` kwarg rejected; (2) missing-credential client construction raised TypeError past the AnthropicError catch; (3) post-call extraction escalated a case already STOPPED by in-call opt-out (InvalidTransition).
- **Fixed:** (1) dropped temperature — extraction determinism now rests on strict schema + rails (PRD §6.2 note); (2) call_claude converts ANY failure to LlmUnavailable; (3) finish_call stands down on terminal cases — FR-5.2 outranks extraction.
- **Decided:** FR-7.2 behaviors enforced as code rails so the adversarial six are CI-provable without live models — a compromised LLM can annoy, never act. Research (logged earlier): Sarvam primary confirmed (Saaras/Saarika beat GPT-4o/Gemini/Deepgram on Indic WER); Claude models per §6.1 split.
- **PENDING (needs keys):** live golden-set ≥90% run needs ANTHROPIC_API_KEY; console STT/TTS manual check needs SARVAM_API_KEY. Both skip honestly, never fake green.
- **Next:** close pending gates when keys land, then Phase 8 — 3-arm eval harness.
