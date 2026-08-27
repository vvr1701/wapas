# CLAUDE.md — Operating instructions for AI-assisted development on Wapas

## What this project is
Wapas is an AI Revenue Recovery agent for the Razorpay AI Buildathon 2026 (Track 3): it detects revenue at risk (failed subscriptions, abandoned checkouts, overdue invoices) on Razorpay **test-mode** APIs, diagnoses root cause, executes bounded interventions (smart retries, payment-link nudges, a Hinglish voice agent with promise-to-pay capture), and **measures** money recovered vs a baseline — with guardrails, escalation, and a hash-chained audit log.

## Source of truth
`PRD.md` in the repo root. If anything here or in code conflicts with the PRD, **the PRD wins.** Any scope change requires a one-line entry in the PRD Changelog *before* implementation. If a requirement seems wrong or infeasible, stop and say so — do not silently reinterpret it.

## How we work (phase protocol)
1. Work on **exactly one phase per session**, from PRD §13.1. Do not start the next phase.
2. Start each session by restating the phase's Scope (FR IDs) and Exit Gate.
3. Implement with tests. For Phase 4 (guardrails): **tests first, then code.**
4. A phase is done only when every Exit Gate line passes — show the actual command output (pytest summary, make output). Never claim green without running.
5. Commit at the phase boundary: `phase-N: <name> — gates green`. Conventional, meaningful intermediate commits are fine.
6. End every session by appending to `BUILD_LOG.md`: *Shipped / Broke / Fixed / Decided(+why) / Next.*
7. When blocked: write the blocker + 2–3 options with trade-offs into BUILD_LOG, pick nothing, and stop for human review.

## Hard rules (non-negotiable)
- **Never fabricate** data, metrics, test results, benchmark numbers, or citations. If a number doesn't come from a real run, it does not exist.
- **Never modify `simulator/behavior_model.py`** outside Phase 1. Improving eval results by touching the simulated world is gaming (PRD FR-1.4) and disqualifying by design. Tune `config/policies.yaml` instead.
- **LLMs never gate actions.** Permission logic (caps, windows, opt-outs, budgets) is deterministic code only (PRD §6.1). LLM outputs are pydantic-validated JSON; invalid → 1 retry → deterministic fallback. The system must never crash or act on malformed model output.
- **Secrets:** only via `.env` (documented in `.env.example`). Never write a key into code, tests, logs, or commits. `detect-secrets` must stay clean.
- **Audit symmetry:** no write to business tables without a paired audit record (PRD FR-10.2). Every executed action carries an idempotency key.
- **Tone lint:** customer-facing copy contains no threats, shame, or legal-action language (PRD C-5); disclosure line always first in voice (FR-7.2).
- Do not add dependencies, services, or clever abstractions the PRD doesn't need. Boring and tested beats impressive and fragile.

## Code standards
- Python 3.12, type hints on all core modules, pydantic v2 models at every module boundary.
- Functions ≤ ~60 lines; each module's docstring states its single responsibility.
- `ruff` clean, `pytest` green before any "done" claim; keep CI green — never leave main red.
- Prompts live in `agent/prompts/` as files; every LLM call logs prompt_hash, model, tokens, latency, cost.
- Structured logging with `case_id` correlation once Phase 6+.

## Commands (the only definitions of done)
- `make test` · `make seed` · `make eval SEED=42` · `make verify-audit` · `make dashboard` · `ruff check .`

## Context notes
- Razorpay test mode cannot force arbitrary failures at scale → the simulator injects events using Razorpay's real error-code taxonomy; everything simulated is disclosed in `SIMULATION.md`. Keep that file truthful as behavior evolves.
- Verify current Razorpay API and Sarvam/ElevenLabs docs at point of use; do not code against remembered APIs without checking.
- Deadline: submission Sept 3, 2026 (hard close Sept 5). When time-constrained, follow the cut order in PRD §12 — never cut the "never cut" list.
