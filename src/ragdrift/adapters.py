"""Eval-suite adapters: run the sibling tools' REAL code, never reimplement it.

- GovDemoAdapter: imports rag-governance-demo's src.eval and runs its real
  eval harness (37 cases: groundedness, citations, refusals, cross-domain
  isolation, red-team attack cases).
- RedteamAdapter: imports rag-redteam's runner and runs its real attack
  battery against the demo target.

Both adapters return a flat metrics dict {name: value in [0,1]} plus
counts, so the drift engine stays tool-agnostic.
"""

import json
import sys
import time
import traceback
from pathlib import Path


class AdapterError(Exception):
    """Raised when a sibling eval suite cannot be executed."""


def _utcnow():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class GovDemoAdapter:
    """Runs rag-governance-demo's real eval harness via import."""

    name = "gov-demo"

    def __init__(self, demo_path):
        self.demo_path = Path(demo_path)
        if not (self.demo_path / "src" / "eval.py").exists():
            raise AdapterError(f"not a rag-governance-demo checkout: {demo_path}")

    def version(self):
        return {"demo_path": str(self.demo_path)}

    def run(self):
        src = str(self.demo_path / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        try:
            import importlib
            ev = importlib.import_module("eval")
            importlib.reload(ev)  # fresh module state per run
        except Exception as exc:
            raise AdapterError(f"could not import demo eval: {exc}\n{traceback.format_exc(limit=3)}")
        try:
            cases = json.loads((self.demo_path / "evals" / "test_set.json").read_text())
            results = ev.run_eval(str(self.demo_path), verbose=False)
        except Exception as exc:
            raise AdapterError(f"demo eval failed: {exc}\n{traceback.format_exc(limit=3)}")
        id2case = {c["id"]: c for c in cases}
        metrics, counts = {}, {}
        total = len(results)
        passed = sum(1 for r in results if r["pass"])
        metrics["eval.overall_pass_rate"] = passed / total if total else 1.0
        counts["eval.cases_total"] = total
        counts["eval.cases_passed"] = passed

        def rate(pred):
            sel = [r for r in results if pred(r)]
            if not sel:
                return None
            return sum(1 for r in sel if r["pass"]) / len(sel), len(sel)

        answer = rate(lambda r: id2case[r["id"]].get("expect") == "answer")
        if answer:
            metrics["eval.groundedness_rate"], counts["eval.answer_cases"] = answer
        refuse = rate(lambda r: id2case[r["id"]].get("expect") in ("refuse", "escalate_or_answer"))
        if refuse:
            metrics["eval.refusal_handling_rate"], counts["eval.refusal_cases"] = refuse
        attack = rate(lambda r: "attack" in r["id"])
        if attack:
            metrics["eval.redteam_sub_rate"], counts["eval.attack_cases"] = attack
        domains = sorted({id2case[r["id"]].get("domain", "?") for r in results})
        for d in domains:
            dr = rate(lambda r, d=d: id2case[r["id"]].get("domain") == d)
            if dr:
                metrics[f"eval.domain.{d}_pass_rate"], counts[f"eval.domain.{d}_cases"] = dr[0], dr[1]
        regressed = [r["id"] for r in results if not r["pass"]]
        return {"metrics": metrics, "counts": counts,
                "regressed_cases": regressed, "ran_at": _utcnow()}


class RedteamAdapter:
    """Runs rag-redteam's real attack battery against the demo target."""

    name = "redteam"

    def __init__(self, redteam_path, demo_path, families=None):
        self.redteam_path = Path(redteam_path)
        self.demo_path = Path(demo_path)
        self.families = families
        if not (self.redteam_path / "ragredteam" / "runner.py").exists():
            raise AdapterError(f"not a rag-redteam checkout: {redteam_path}")

    def version(self):
        return {"redteam_path": str(self.redteam_path),
                "demo_path": str(self.demo_path),
                "families": self.families or "all"}

    def run(self):
        pkg = str(self.redteam_path)
        if pkg not in sys.path:
            sys.path.insert(0, pkg)
        try:
            import importlib
            runner = importlib.import_module("ragredteam.runner")
            importlib.reload(runner)
            adapters_mod = importlib.import_module("ragredteam.adapters")
            importlib.reload(adapters_mod)
        except Exception as exc:
            raise AdapterError(f"could not import ragredteam: {exc}\n{traceback.format_exc(limit=3)}")
        try:
            target = adapters_mod.RagGovernanceDemoTarget(str(self.demo_path))
            suite = runner.run_suite(target, families=self.families)
        except Exception as exc:
            raise AdapterError(f"redteam run failed: {exc}\n{traceback.format_exc(limit=3)}")
        metrics, counts = {}, {}
        metrics["redteam.attack_pass_rate"] = suite.overall_pass_rate
        total = sum(fs.total for fs in suite.families)
        passed = sum(fs.passed for fs in suite.families)
        counts["redteam.attacks_total"] = total
        counts["redteam.attacks_passed"] = passed
        for fs in suite.families:
            metrics[f"redteam.family.{fs.family}_pass_rate"] = fs.pass_rate
            counts[f"redteam.family.{fs.family}_total"] = fs.total
        if suite.control_pass_rate is not None:
            metrics["redteam.control_pass_rate"] = suite.control_pass_rate
        failed_families = [fs.family for fs in suite.families
                           if fs.pass_rate < 1.0]
        return {"metrics": metrics, "counts": counts,
                "regressed_cases": [f"family:{f}" for f in failed_families],
                "ran_at": _utcnow()}
