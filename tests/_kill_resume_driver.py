"""Driver for the NFR-2 kill-and-resume test. Runs a reduced arm-C eval loop
against the DB path in argv[1], committing per step; argv[2]=slow adds a sleep
per step so the test can SIGKILL it mid-batch. Re-running on the same DB must
produce zero duplicate executions — ingestion is idempotent, plans are not
re-created, and idempotency keys make execution at-most-once."""

import copy
import sys
import time
from datetime import timedelta
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from agent.cases import CaseState, transition
from agent.detector import from_simulator, ingest
from agent.diagnosis import diagnose_case, load_error_map
from agent.policy import load_policy, plan_case
from evalh.run_batch import _step, _world_cases
from ledger.db import get_engine
from simulator.event_generator import SIM_NOW, generate_batch

SEED = 5


def main() -> None:
    db_path = Path(sys.argv[1])
    slow = len(sys.argv) > 2
    cfg = copy.deepcopy(yaml.safe_load(Path("config/sim_config.yaml").read_text()))
    cfg["batch"]["size"] = 30
    policy = load_policy()
    events = generate_batch(SEED, cfg, {})
    cases = _world_cases(events)
    world_by_entity = {c.entity_id: c for c in cases}
    error_map = load_error_map()

    with Session(get_engine(db_path)) as db:
        revenue_events = [from_simulator(e.model_dump(mode="json")) for e in events]
        opened = ingest(db, revenue_events, SIM_NOW)  # idempotent: resume opens nothing
        by_entity = {e.entity_id: e for e in revenue_events}
        for case in opened:
            diagnose_case(db, case, by_entity[case.entity_id], error_map)
            plan_case(db, case, policy, SIM_NOW)
            for st in (CaseState.GATED, CaseState.EXECUTING, CaseState.AWAITING_OUTCOME):
                transition(db, case, st)
        db.commit()
        for d in range(10):
            for hour in (6, 15):
                now = (SIM_NOW + timedelta(days=d)).replace(hour=hour, minute=0)
                _step(db, policy, SEED, now, world_by_entity, [])
                db.commit()
                if slow:
                    time.sleep(0.15)
    print("DONE")


if __name__ == "__main__":
    main()
