# Wapas — AI Revenue Recovery Agent

> **Wapas** (Hindi: "back / return") — *Revenue that slipped away, brought wapas.*

Razorpay AI Buildathon 2026 · Track 3. Detects revenue at risk (failed subscriptions,
abandoned checkouts, overdue invoices) on Razorpay test-mode APIs, diagnoses root cause,
executes bounded interventions, and **measures** money recovered vs a baseline.

**Status: Phase 0 (scaffold).** Full spec in [PRD.md](PRD.md). Build journal in [BUILD_LOG.md](BUILD_LOG.md).

## Run
```
cp .env.example .env   # add your test-mode keys
make test
```
Remaining targets (`make seed`, `make eval`, `make dashboard`, `make verify-audit`) land phase by phase per PRD §13.1.
