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
