"""Run store: append-only JSONL run records + pinned-baseline state."""

import json
import time
import uuid
from pathlib import Path


def _utcnow():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class RunStore:
    def __init__(self, store_dir):
        self.dir = Path(store_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.runs_path = self.dir / "runs.jsonl"
        self.state_path = self.dir / "state.json"

    def append_run(self, adapter_results, config, notes=""):
        run_id = uuid.uuid4().hex[:12]
        record = {
            "run_id": run_id,
            "ran_at": _utcnow(),
            "notes": notes,
            "config": config,
            "adapters": {
                name: {"metrics": res["metrics"], "counts": res["counts"],
                       "regressed_cases": res["regressed_cases"],
                       "version": res.get("version", {})}
                for name, res in adapter_results.items()
            },
        }
        with self.runs_path.open("a") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def runs(self):
        if not self.runs_path.exists():
            return []
        out = []
        for line in self.runs_path.read_text().splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def get_run(self, run_id):
        for r in self.runs():
            if r["run_id"] == run_id:
                return r
        return None

    def set_baseline(self, run_id):
        state = self.state()
        state["baseline_run_id"] = run_id
        state["baseline_set_at"] = _utcnow()
        self.state_path.write_text(json.dumps(state, indent=2, sort_keys=True))

    def state(self):
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        return {}

    def baseline(self):
        bid = self.state().get("baseline_run_id")
        return self.get_run(bid) if bid else None
