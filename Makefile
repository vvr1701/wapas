.PHONY: test seed simulate eval dashboard verify-audit lint api web demo-reset

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
	uv run streamlit run dashboard/app.py

api:
	uv run uvicorn channels.voice.console:app --port 8000

web:
	cd webapp && npm run dev

demo-reset:
	rm -f data/demo.db
