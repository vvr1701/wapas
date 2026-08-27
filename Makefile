.PHONY: test seed simulate eval dashboard verify-audit lint

test:
	uv run pytest

lint:
	uv run ruff check .

seed:
	@echo "TODO Phase 1: uv run python -m simulator.seed_razorpay" && exit 1

simulate:
	@echo "TODO Phase 1: uv run python -m simulator.event_generator --seed $(or $(SEED),42)" && exit 1

eval:
	@echo "TODO Phase 8: uv run python -m evalh.run_batch --seed $(or $(SEED),42)" && exit 1

verify-audit:
	@echo "TODO Phase 2: uv run python -m ledger.audit --verify" && exit 1

dashboard:
	@echo "TODO Phase 9: uv run streamlit run dashboard/app.py" && exit 1
