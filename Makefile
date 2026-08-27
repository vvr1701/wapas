.PHONY: test seed simulate eval dashboard verify-audit lint

test:
	uv run pytest

lint:
	uv run ruff check .

seed:
	uv run python -m simulator.seed_razorpay

simulate:
	uv run python -m simulator.event_generator --seed $(or $(SEED),42)

eval:
	uv run python -m evalh.run_batch --seed $(or $(SEED),42)

verify-audit:
	uv run python -m ledger.audit --verify

dashboard:
	@echo "TODO Phase 9: uv run streamlit run dashboard/app.py" && exit 1
