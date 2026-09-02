"""Phase 1 exit-gate tests: determinism (FR-1.2/1.3), seeder idempotency (FR-1.1),
and the anti-circularity import guard (FR-1.3/1.4)."""

from pathlib import Path

import yaml

from simulator import behavior_model as bm
from simulator.event_generator import batch_hash, generate_batch
from simulator.seed_razorpay import Seeder

CFG = yaml.safe_load(Path("config/sim_config.yaml").read_text())
REPO = Path(__file__).resolve().parent.parent


# --- FR-1.3: hidden state & reactions are deterministic per seed ---------------


def test_hidden_state_deterministic():
    a = bm.sample_hidden_state(42, "cust_0001")
    b = bm.sample_hidden_state(42, "cust_0001")
    assert a == b
    assert bm.sample_hidden_state(43, "cust_0001") != a


def test_world_hash_stable_and_seed_sensitive():
    ids = [f"cust_{i:04d}" for i in range(50)]
    assert bm.world_hash(42, ids) == bm.world_hash(42, list(reversed(ids)))
    assert bm.world_hash(42, ids) != bm.world_hash(7, ids)


def test_reactions_deterministic():
    h = bm.sample_hidden_state(42, "cust_0002")
    kw = dict(
        seed=42,
        customer_id="cust_0002",
        hidden=h,
        kind="nudge",
        channel="whatsapp",
        day_of_month=7,
        contacts_so_far=1,
        attempt_no=1,
    )
    assert bm.react(**kw) == bm.react(**kw)


def test_annoyed_customer_never_pays_and_may_opt_out():
    h = bm.sample_hidden_state(42, "cust_0003")
    r = bm.react(
        42, "cust_0003", h, "nudge", "email", 7, contacts_so_far=h.annoyance_threshold, attempt_no=9
    )
    assert not r.pays and r.disengaged


# --- FR-1.2: batch fully determined by seed ------------------------------------


def test_batch_hash_reproducible():
    h1 = batch_hash(generate_batch(42, CFG, {}))
    h2 = batch_hash(generate_batch(42, CFG, {}))
    assert h1 == h2
    assert batch_hash(generate_batch(43, CFG, {})) != h1


def test_batch_shape():
    events = generate_batch(42, CFG, {})
    assert len(events) == CFG["batch"]["size"]
    cats = {e.category for e in events}
    assert cats == {"L1", "L2", "L3"}
    for e in events:
        if e.category == "L1":
            assert e.error_code and e.error_reason
        if e.category == "L3":
            assert e.due_date is not None


# --- FR-1.1: seeder idempotency via fake client --------------------------------


class _FakeResource:
    def __init__(self, counter: dict, kind: str):
        self.counter, self.kind = counter, kind

    def create(self, payload: dict) -> dict:
        self.counter[self.kind] = self.counter.get(self.kind, 0) + 1
        return {"id": f"{self.kind}_{self.counter[self.kind]:05d}"}


class _FakeClient:
    def __init__(self):
        self.counter: dict = {}
        for kind in ("customer", "plan", "subscription", "order", "invoice"):
            setattr(self, kind, _FakeResource(self.counter, kind))


def test_seeder_idempotent(tmp_path):
    reg_path = tmp_path / "seed_registry.json"
    client = _FakeClient()
    first = Seeder(client, CFG, reg_path).run()
    creates_after_first = dict(client.counter)
    second = Seeder(client, CFG, reg_path).run()
    assert client.counter == creates_after_first  # zero new API creates on re-run
    assert first == second
    assert reg_path.exists()


# --- FR-1.3/1.4: the agent can never see hidden state --------------------------


def test_agent_never_imports_behavior_model():
    forbidden_dirs = ["agent", "channels", "ledger", "dashboard"]
    offenders = [
        str(f)
        for d in forbidden_dirs
        for f in (REPO / d).rglob("*.py")
        if "behavior_model" in f.read_text()
    ]
    assert offenders == [], f"hidden-state access from: {offenders}"


def test_behavior_model_bytes_frozen():
    """Hard rule (CLAUDE.md): the world model froze in phase 1. Pinning the exact
    bytes makes 'we never tuned the simulator to flatter the agent' a CI fact
    rather than a claim. If this ever fails legitimately, PRD changelog first."""
    import hashlib

    digest = hashlib.sha256(Path("simulator/behavior_model.py").read_bytes()).hexdigest()
    assert digest == "1ff7f2959ccf578996d4a2f267a7c65eb95795e18a6f1704ae3145bfa2194caa"
