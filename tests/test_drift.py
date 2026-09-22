"""Tests for rag-eval-drift: drift rules, dedup, audit chain, adapters."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ragdrift.drift import detect
from ragdrift.store import RunStore
from ragdrift.alerts import Alerter
from ragdrift.audit import AuditLog
from ragdrift.adapters import GovDemoAdapter, AdapterError


def _run(metrics, run_id="r1", regressed=()):
    return {
        "run_id": run_id, "ran_at": "2026-01-01T00:00:00Z",
        "adapters": {
            "test": {"metrics": dict(metrics), "counts": {},
                     "regressed_cases": list(regressed), "version": {}},
        },
    }


class DriftRulesTest(unittest.TestCase):
    def test_genuine_regression_flagged(self):
        base = _run({"eval.overall_pass_rate": 1.0})
        cur = _run({"eval.overall_pass_rate": 0.919},
                   regressed=["cold-1", "hr-2"])
        f = detect(base, cur)
        thr = [x for x in f if x["rule"] == "threshold"]
        self.assertEqual(len(thr), 1)
        self.assertEqual(thr[0]["metric"], "eval.overall_pass_rate")
        self.assertEqual(thr[0]["direction"], "down")
        self.assertIn("cold-1", thr[0]["evidence"]["newly_regressed"])

    def test_noise_not_flagged(self):
        base = _run({"eval.overall_pass_rate": 1.0})
        cur = _run({"eval.overall_pass_rate": 0.998})  # below epsilon
        self.assertEqual(detect(base, cur), [])

    def test_improvement_never_alerts_as_drift(self):
        base = _run({"redteam.attack_pass_rate": 0.85})
        cur = _run({"redteam.attack_pass_rate": 0.95})
        f = detect(base, cur)
        self.assertTrue(all(x["rule"] == "improvement" for x in f))
        self.assertEqual(len(f), 1)

    def test_new_metric_no_baseline_skipped(self):
        base = _run({"a": 1.0})
        cur = _run({"a": 1.0, "brand.new_metric": 0.1})
        f = detect(base, cur)
        self.assertFalse(any(x["metric"] == "brand.new_metric" for x in f))

    def test_trend_rule_catches_slow_decay(self):
        base = _run({"eval.groundedness_rate": 1.0}, run_id="b")
        h1 = _run({"eval.groundedness_rate": 0.99}, run_id="h1")
        h2 = _run({"eval.groundedness_rate": 0.98}, run_id="h2")
        cur = _run({"eval.groundedness_rate": 0.97}, run_id="c")
        f = detect(base, cur, history_runs=[h1, h2],
                   threshold=0.05, trend_window=3, trend_epsilon=0.005)
        tr = [x for x in f if x["rule"] == "trend"]
        self.assertEqual(len(tr), 1)
        self.assertEqual(tr[0]["metric"], "eval.groundedness_rate")

    def test_trend_rule_not_fooled_by_bounce(self):
        base = _run({"eval.groundedness_rate": 1.0}, run_id="b")
        h1 = _run({"eval.groundedness_rate": 0.99}, run_id="h1")
        h2 = _run({"eval.groundedness_rate": 0.995}, run_id="h2")  # up
        cur = _run({"eval.groundedness_rate": 0.97}, run_id="c")
        f = detect(base, cur, history_runs=[h1, h2], threshold=0.05)
        self.assertFalse(any(x["rule"] == "trend" for x in f))

    def test_threshold_takes_precedence_over_trend(self):
        base = _run({"m": 1.0}, run_id="b")
        h1 = _run({"m": 0.9}, run_id="h1")
        h2 = _run({"m": 0.85}, run_id="h2")
        cur = _run({"m": 0.8}, run_id="c")
        f = detect(base, cur, history_runs=[h1, h2])
        rules = {x["rule"] for x in f if x["metric"] == "m"}
        self.assertEqual(rules, {"threshold"})


class DedupTest(unittest.TestCase):
    def test_no_double_page(self):
        with tempfile.TemporaryDirectory() as d:
            al = Alerter(d)
            findings = [{"metric": "eval.overall_pass_rate", "rule": "threshold",
                         "baseline": 1.0, "current": 0.9, "delta": -0.1,
                         "direction": "down", "evidence": {}}]
            first = al.alert("r1", findings, 0.05)
            second = al.alert("r2", findings, 0.05)
            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 0)
            self.assertEqual(len(al.outbox()), 1)

    def test_recovery_clears_dedup(self):
        with tempfile.TemporaryDirectory() as d:
            al = Alerter(d)
            findings = [{"metric": "m", "rule": "threshold",
                         "baseline": 1.0, "current": 0.9, "delta": -0.1,
                         "direction": "down", "evidence": {}}]
            al.alert("r1", findings, 0.05)
            # metric recovers to within half-threshold of baseline
            al.clear_recovered([], {"m": 0.99}, {"m": 1.0}, 0.05)
            again = al.alert("r3", findings, 0.05)
            self.assertEqual(len(again), 1)

    def test_improvements_never_write_alerts(self):
        with tempfile.TemporaryDirectory() as d:
            al = Alerter(d)
            findings = [{"metric": "m", "rule": "improvement",
                         "baseline": 0.8, "current": 0.9, "delta": 0.1,
                         "direction": "up", "evidence": {}}]
            self.assertEqual(al.alert("r1", findings, 0.05), [])
            self.assertEqual(al.outbox(), [])


class StoreTest(unittest.TestCase):
    def test_baseline_pinning(self):
        with tempfile.TemporaryDirectory() as d:
            st = RunStore(d)
            r1 = st.append_run({"a": {"metrics": {"m": 1.0}, "counts": {},
                                     "regressed_cases": [], "version": {}}},
                               {"threshold": 0.05})
            self.assertIsNone(st.baseline())
            st.set_baseline(r1["run_id"])
            self.assertEqual(st.baseline()["run_id"], r1["run_id"])
            r2 = st.append_run({"a": {"metrics": {"m": 0.9}, "counts": {},
                                     "regressed_cases": [], "version": {}}},
                               {"threshold": 0.05})
            self.assertEqual(len(st.runs()), 2)
            self.assertEqual(st.get_run(r2["run_id"])["run_id"], r2["run_id"])
            self.assertIsNone(st.get_run("nope"))


class AuditChainTest(unittest.TestCase):
    def test_chain_intact(self):
        with tempfile.TemporaryDirectory() as d:
            a = AuditLog(d)
            a.append("run", {"run_id": "r1"})
            a.append("alert", {"metric": "m"})
            ok, msg = a.verify()
            self.assertTrue(ok, msg)

    def test_tamper_detected(self):
        with tempfile.TemporaryDirectory() as d:
            a = AuditLog(d)
            a.append("run", {"run_id": "r1"})
            a.append("run", {"run_id": "r2"})
            lines = a.path.read_text().splitlines()
            rec = json.loads(lines[1])
            rec["payload"]["run_id"] = "rX"  # tamper, keep old hash
            lines[1] = json.dumps(rec, sort_keys=True)
            a.path.write_text("\n".join(lines) + "\n")
            ok, _ = a.verify()
            self.assertFalse(ok)

    def test_link_break_detected(self):
        with tempfile.TemporaryDirectory() as d:
            a = AuditLog(d)
            a.append("run", {"run_id": "r1"})
            a.append("run", {"run_id": "r2"})
            lines = a.path.read_text().splitlines()
            a.path.write_text(lines[0] + "\n" + lines[1] + "\n" + lines[1] + "\n")
            ok, _ = a.verify()
            self.assertFalse(ok)


class AdapterErrorTest(unittest.TestCase):
    def test_bad_demo_path(self):
        with self.assertRaises(AdapterError):
            GovDemoAdapter("/nonexistent/path")

    def test_gov_demo_real_run(self):
        demo = Path(__file__).resolve().parent.parent.parent / \
            "rag-governance-demo"
        if not (demo / "src" / "eval.py").exists():
            self.skipTest("sibling checkout not present")
        res = GovDemoAdapter(str(demo)).run()
        self.assertIn("eval.overall_pass_rate", res["metrics"])
        self.assertEqual(res["counts"]["eval.cases_total"], 37)


if __name__ == "__main__":
    unittest.main()
