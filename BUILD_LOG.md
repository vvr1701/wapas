# BUILD_LOG

Daily: Shipped / Broke / Fixed / Decided (+why) / Next.

## Aug 27, 2026 — Phase 0: Scaffold & CI
- **Shipped:** repo structure per PRD §11.1, pyproject + uv.lock (py3.12), Makefile (test/lint live; seed/eval/dashboard/verify-audit stubbed to fail loudly), .env.example, CI (ruff lint+format+pytest), detect-secrets pre-commit + clean baseline, placeholder test.
- **Broke:** nothing.
- **Fixed:** n/a.
- **Decided:** uv over pip-tools (already installed, manages py3.12 itself on a py3.14 host). Runtime deps deferred to the phase that needs them — lockfile churn beats speculative pins.
- **Next:** Phase 1 — Merchant world (FR-1.1–1.4, 1.6). Needs Razorpay test-mode keys in .env.
