"""FR-11.1 exit-gate tests, CI-safe on a reduced batch: identical metrics across
two runs, world-hash equality across arms, non-empty exception list, and the
attribution invariants that keep the numbers honest."""

import copy
from pathlib import Path

import pytest
import yaml

from agent.policy import load_policy
from evalh.arms import run_arm_a, run_arm_b
from evalh.metrics import assemble_metrics
from evalh.run_batch import _world_cases, run_arm_c, write_exceptions_md
from simulator import behavior_model as bm
from simulator.event_generator import SIM_NOW, generate_batch

CFG = yaml.safe_load(Path("config/sim_config.yaml").read_text())
SMALL = copy.deepcopy(CFG)
SMALL["batch"]["size"] = 40
DAYS = 14


def _run(seed: int, tmp_path: Path, tag: str) -> dict:
    events = generate_batch(seed, SMALL, {})
    cases = _world_cases(events)
    policy = load_policy()
    arm_a = run_arm_a(seed, cases, SIM_NOW, DAYS)
    arm_b = run_arm_b(seed, cases, SIM_NOW, DAYS)
    arm_c, extras = run_arm_c(
        seed, events, cases, SIM_NOW, DAYS, tmp_path / f"eval_{tag}.db", policy
    )
    metrics = assemble_metrics(cases, arm_a, arm_b, arm_c, extras)
    return metrics, extras


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("eval")
    m1, e1 = _run(42, tmp, "r1")
    m2, e2 = _run(42, tmp, "r2")
    return m1, e1, m2, e2


def test_two_runs_identical_metrics(runs):
    m1, _, m2, _ = runs
    assert m1 == m2


def test_world_hash_identical_across_arms():
    events = generate_batch(42, SMALL, {})
    ids = sorted({e.customer_id for e in events})
    assert bm.world_hash(42, ids) == bm.world_hash(42, ids) == bm.world_hash(42, ids)


def test_exceptions_nonempty_and_rendered(runs, tmp_path):
    _, extras, _, _ = runs
    assert extras["exceptions"], "an honest run has cases it could not recover"
    out = tmp_path / "EXCEPTIONS.md"
    write_exceptions_md(extras["exceptions"], out, seed=42)
    text = out.read_text()
    assert "could NOT recover" in text and extras["exceptions"][0]["entity_id"] in text


def test_attribution_invariants(runs):
    m, extras, _, _ = runs
    h = m["headline"]
    assert h["stops_honored"] == 1.0  # the number that must print 100%
    assert extras["actions_after_optout"] == 0
    assert h["at_risk_inr"] == m["batch"]["at_risk_inr"] > 0
    # raw credit can never exceed what was at risk
    for arm in ("A", "B", "C"):
        assert 0 <= h["recovered_raw_inr"][arm] <= h["at_risk_inr"]
    # adjusted is raw minus natural expectation, so strictly less than raw
    assert h["recovered_adj_inr"]["C"] < h["recovered_raw_inr"]["C"]
    assert m["promises"]["kept"] <= m["promises"]["made"]


def test_different_seed_different_world(runs):
    m1, _, _, _ = runs
    events = generate_batch(7, SMALL, {})
    ids = sorted({e.customer_id for e in events})
    assert bm.world_hash(7, ids) != bm.world_hash(42, ids)
