# SIMULATION.md — the honesty ledger (FR-1.6)

Razorpay test mode cannot force arbitrary payment failures at scale, so parts of
this world are simulated. This file states exactly what is real and what is not,
and stays truthful as behavior evolves. Everything the eval numbers rest on is
listed here.

## Real (live Razorpay test-mode API objects)

| Element | How |
|---|---|
| Customers, plan, subscriptions, orders, invoices | Created by `simulator/seed_razorpay.py` via the Razorpay Python SDK; ids in `data/seed_registry.json`. L2 entities are Orders, not payment links — test mode caps payment links at 30 total, so the link budget is reserved for per-nudge links (FR-6.2) |
| Payment links sent in nudges | Created per-case via the Payment Links API |
| Payments that close cases | Completed in the browser with Razorpay test cards/UPI and observed via API polling |

## Simulated (and why)

| Element | How | Why |
|---|---|---|
| Failure events (L1 charge failures, L2 abandonment, L3 overdue) | `simulator/event_generator.py` injects a seed-determined batch using Razorpay's error-code taxonomy (starter map from PRD Appendix A; field shape mirrors the payment entity's `error_code` / `error_reason` / `error_description`) | Test mode cannot trigger real mandate failures, OTP drop-offs, or aged receivables at scale |
| Customer behavior (whether an intervention works) | `simulator/behavior_model.py`: hidden per-customer state — liquidity day (salary-day clustering 1st/7th/15th), channel responsiveness, willingness to pay, annoyance threshold, opt-out propensity. Reactions are probabilistic, deterministic per seed | There are no real customers; behavior must be synthetic to measure anything |
| Nudge delivery | Rendered to a local outbox (`data/outbox/`), not actually emailed/WhatsApped | No real recipients exist; avoids any real-world messaging |
| Synthetic PII | Names/emails/phones generated in `seed_razorpay.py` | No real personal data, per DPDP-aligned posture (PRD C-6) |
| Entity ids when the world is not yet seeded | `sim_`-prefixed synthetic ids | Lets the deterministic generator and tests run offline |

## Anti-circularity guarantees (FR-1.4)

- The behavior model is **frozen outside Phase 1** and identical across all three
  eval arms; the harness asserts an identical `world_hash` before running.
- The agent **cannot read hidden state** — it only observes outcomes. Enforced by
  `tests/test_simulator.py::test_agent_never_imports_behavior_model`.
- The agent is tuned only via `config/policies.yaml` — never via this simulator.
