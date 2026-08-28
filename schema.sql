-- schema.sql — generated from ledger/db.py (SQLAlchemy models) so reviewers
-- can read the data model without running code (PRD §7).

CREATE TABLE audit_log (
	id INTEGER NOT NULL, 
	ts VARCHAR NOT NULL, 
	case_id INTEGER, 
	actor VARCHAR NOT NULL, 
	event_type VARCHAR NOT NULL, 
	payload_json TEXT NOT NULL, 
	rule_id VARCHAR, 
	policy_version_hash VARCHAR, 
	prev_record_hash VARCHAR(64) NOT NULL, 
	record_hash VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE customers (
	id INTEGER NOT NULL, 
	customer_id VARCHAR NOT NULL, 
	opted_out BOOLEAN NOT NULL, 
	opt_out_ts VARCHAR, 
	opt_out_source VARCHAR, 
	PRIMARY KEY (id), 
	UNIQUE (customer_id)
);

CREATE TABLE escalations (
	id INTEGER NOT NULL, 
	case_id INTEGER NOT NULL, 
	reason VARCHAR NOT NULL, 
	context_packet_json TEXT NOT NULL, 
	acked_by VARCHAR, 
	acked_ts VARCHAR, 
	created_ts VARCHAR NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE executed_actions (
	id INTEGER NOT NULL, 
	planned_id INTEGER NOT NULL, 
	case_id INTEGER NOT NULL, 
	action_type VARCHAR NOT NULL, 
	channel VARCHAR NOT NULL, 
	idempotency_key VARCHAR NOT NULL, 
	executed_ts VARCHAR NOT NULL, 
	result VARCHAR NOT NULL, 
	external_ref VARCHAR, 
	incentive_inr INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (idempotency_key)
);

CREATE TABLE llm_calls (
	id INTEGER NOT NULL, 
	purpose VARCHAR NOT NULL, 
	prompt_file VARCHAR NOT NULL, 
	prompt_hash VARCHAR(64) NOT NULL, 
	model VARCHAR NOT NULL, 
	tokens_in INTEGER NOT NULL, 
	tokens_out INTEGER NOT NULL, 
	latency_ms INTEGER NOT NULL, 
	cost_usd FLOAT NOT NULL, 
	valid_output BOOLEAN NOT NULL, 
	ts VARCHAR NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE payments_observed (
	id INTEGER NOT NULL, 
	rzp_payment_id VARCHAR NOT NULL, 
	amount_inr INTEGER NOT NULL, 
	method VARCHAR, 
	matched_case_id INTEGER, 
	matched_promise_id INTEGER, 
	attribution_arm VARCHAR, 
	observed_ts VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (rzp_payment_id)
);

CREATE TABLE planned_actions (
	id INTEGER NOT NULL, 
	case_id INTEGER NOT NULL, 
	action_type VARCHAR NOT NULL, 
	channel VARCHAR NOT NULL, 
	scheduled_for VARCHAR NOT NULL, 
	rule_id VARCHAR NOT NULL, 
	rationale TEXT NOT NULL, 
	policy_version_hash VARCHAR(64) NOT NULL, 
	status VARCHAR NOT NULL, 
	incentive_inr INTEGER NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE promises (
	id INTEGER NOT NULL, 
	case_id INTEGER NOT NULL, 
	amount_inr INTEGER NOT NULL, 
	due_date VARCHAR NOT NULL, 
	conditions VARCHAR, 
	confidence FLOAT NOT NULL, 
	status VARCHAR NOT NULL, 
	transcript_ref VARCHAR, 
	created_ts VARCHAR NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE recovery_cases (
	id INTEGER NOT NULL, 
	entity_id VARCHAR NOT NULL, 
	customer_id VARCHAR NOT NULL, 
	category VARCHAR NOT NULL, 
	amount_due_inr INTEGER NOT NULL, 
	currency VARCHAR NOT NULL, 
	state VARCHAR NOT NULL, 
	root_cause VARCHAR, 
	diagnosis_confidence FLOAT, 
	diagnosis_source VARCHAR, 
	due_date VARCHAR, 
	opened_ts VARCHAR NOT NULL, 
	closed_ts VARCHAR, 
	PRIMARY KEY (id), 
	UNIQUE (entity_id)
);

CREATE TABLE revenue_events (
	id INTEGER NOT NULL, 
	event_id VARCHAR NOT NULL, 
	category VARCHAR NOT NULL, 
	source VARCHAR NOT NULL, 
	customer_id VARCHAR NOT NULL, 
	entity_type VARCHAR NOT NULL, 
	entity_id VARCHAR NOT NULL, 
	amount_inr INTEGER NOT NULL, 
	occurred_at VARCHAR NOT NULL, 
	raw_payload TEXT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (event_id)
);
