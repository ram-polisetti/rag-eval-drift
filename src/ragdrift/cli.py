"""CLI: run, bless, status, report, verify, outbox.

Cron-compatible: `ragdrift run --store DIR --demo-path P --redteam-path R`
does one full cycle (eval → drift → alert → audit) and exits 0/1/2.
Exit codes: 0 = no drift, 1 = drift detected (alerts written), 2 = error.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragdrift import __version__
from ragdrift.adapters import GovDemoAdapter, RedteamAdapter, AdapterError
from ragdrift.store import RunStore
from ragdrift.drift import (detect, DEFAULT_THRESHOLD, DEFAULT_TREND_WINDOW,
                            DEFAULT_TREND_EPSILON)
from ragdrift.alerts import Alerter
from ragdrift.audit import AuditLog


def _load_config(path):
    if not path:
        return {}
    return json.loads(Path(path).read_text())


def _git_sha(path):
    import subprocess
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:
        return "unknown"


def cmd_run(args):
    store = RunStore(args.store)
    audit = AuditLog(args.store)
    cfg = _load_config(args.config)
    threshold = cfg.get("threshold", DEFAULT_THRESHOLD)
    trend_window = cfg.get("trend_window", DEFAULT_TREND_WINDOW)
    trend_epsilon = cfg.get("trend_epsilon", DEFAULT_TREND_EPSILON)
    families = cfg.get("redteam_families")

    results = {}
    errors = []
    for name, adapter in (
        ("gov-demo", GovDemoAdapter(args.demo_path)),
        ("redteam", RedteamAdapter(args.redteam_path, args.demo_path,
                                   families=families)),
    ):
        try:
            res = adapter.run()
            res["version"] = adapter.version()
            results[name] = res
        except AdapterError as exc:
            errors.append(f"{name}: {exc}")
    if errors and not results:
        print("ERROR: all adapters failed:\n" + "\n".join(errors), file=sys.stderr)
        return 2

    config = {
        "threshold": threshold, "trend_window": trend_window,
        "trend_epsilon": trend_epsilon,
        "demo_sha": _git_sha(args.demo_path),
        "redteam_sha": _git_sha(args.redteam_path),
        "harness_version": __version__,
    }
    record = store.append_run(results, config, notes=args.notes or "")
    audit.append("run", {"run_id": record["run_id"],
                         "metrics": {k: v for ad in results.values()
                                     for k, v in ad["metrics"].items()}})

    baseline = store.baseline()
    if baseline is None:
        store.set_baseline(record["run_id"])
        audit.append("baseline", {"run_id": record["run_id"],
                                  "reason": "first run auto-pinned"})
        print(f"run {record['run_id']}: baseline pinned (first run). "
              f"metrics: {len(record['adapters'])} adapters ok"
              + (f", ERRORS: {errors}" if errors else ""))
        return 0

    history = [r for r in store.runs()
               if r["run_id"] not in (baseline["run_id"], record["run_id"])]
    findings = detect(baseline, record, history,
                      threshold=threshold, trend_window=trend_window,
                      trend_epsilon=trend_epsilon)
    drift = [f for f in findings if f["rule"] != "improvement"]
    if errors:
        print(f"WARNING: adapter errors: {errors}")

    alerter = Alerter(args.store)
    cur_m = {k: v for ad in results.values() for k, v in ad["metrics"].items()}
    base_m = {k: v for ad in baseline["adapters"].values()
              for k, v in ad["metrics"].items()}
    alerts = alerter.alert(record["run_id"], findings, threshold)
    alerter.clear_recovered(findings, cur_m, base_m, threshold)
    for a in alerts:
        audit.append("alert", {"run_id": record["run_id"],
                               "metric": a["metric"], "rule": a["rule"],
                               "delta": a["delta"]})

    if drift:
        print(f"run {record['run_id']}: DRIFT DETECTED "
              f"({len(drift)} findings, {len(alerts)} new alerts)")
        for f in drift:
            print(f"  - {f['metric']}: {f['baseline']:.1%} → "
                  f"{f['current']:.1%} [{f['rule']}]")
        return 1
    print(f"run {record['run_id']}: no drift "
          f"({len([f for f in findings if f['rule'] == 'improvement'])} improvements noted)")
    return 0


def _table(rows):
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return ["  ".join(r[i].ljust(widths[i]) for i in range(len(r)))
            for r in rows]


def cmd_status(args):
    store = RunStore(args.store)
    runs = store.runs()
    baseline = store.baseline()
    if not runs:
        print("no runs yet")
        return 0
    latest = runs[-1]
    base_m = {}
    if baseline:
        base_m = {k: v for ad in baseline["adapters"].values()
                  for k, v in ad["metrics"].items()}
    cur_m = {k: v for ad in latest["adapters"].values()
             for k, v in ad["metrics"].items()}
    rows = [["metric", "baseline", "latest", "delta"]]
    for m in sorted(cur_m):
        b = base_m.get(m)
        rows.append([m, f"{b:.1%}" if b is not None else "—",
                     f"{cur_m[m]:.1%}",
                     f"{cur_m[m]-b:+.1%}" if b is not None else "—"])
    print(f"latest run: {latest['run_id']} ({latest['ran_at']})")
    print(f"baseline: {baseline['run_id'] if baseline else 'none'}")
    print("\n".join(_table(rows)))
    return 0


def cmd_report(args):
    store = RunStore(args.store)
    runs = store.runs()[-args.last:]
    if not runs:
        print("no runs yet")
        return 0
    metrics = sorted({k for r in runs for ad in r["adapters"].values()
                      for k in ad["metrics"]})
    key = [m for m in metrics
           if m in ("eval.overall_pass_rate", "redteam.attack_pass_rate")]
    key = key or metrics[:6]
    rows = [["run", "time"] + key]
    for r in runs:
        m = {k: v for ad in r["adapters"].values() for k, v in ad["metrics"].items()}
        rows.append([r["run_id"][:8], r["ran_at"][:16]] +
                    [f"{m.get(k, float('nan')):.1%}" if k in m else "—"
                     for k in key])
    print("\n".join(_table(rows)))
    return 0


def cmd_bless(args):
    store = RunStore(args.store)
    audit = AuditLog(args.store)
    run = store.get_run(args.run_id)
    if not run:
        print(f"unknown run: {args.run_id}", file=sys.stderr)
        return 2
    store.set_baseline(args.run_id)
    audit.append("baseline", {"run_id": args.run_id, "reason": "manual bless"})
    # a new baseline resets alert dedup: old drifts are no longer comparable
    alerter = Alerter(args.store)
    state = alerter._state()
    state["active"] = {}
    alerter._save(state)
    print(f"baseline pinned to run {args.run_id}")
    return 0


def cmd_verify(args):
    ok, msg = AuditLog(args.store).verify()
    print(msg)
    return 0 if ok else 2


def cmd_outbox(args):
    names = Alerter(args.store).outbox()
    print(f"{len(names)} alerts in outbox")
    for n in names:
        print("  " + n)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ragdrift",
                                 description="RAG eval-drift harness")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="one full cycle: eval, drift, alert")
    p.add_argument("--store", required=True, help="state directory")
    p.add_argument("--demo-path", required=True,
                   help="rag-governance-demo checkout")
    p.add_argument("--redteam-path", required=True,
                   help="rag-redteam checkout")
    p.add_argument("--config", help="JSON config file")
    p.add_argument("--notes", default="", help="notes for this run")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("bless", help="pin a run as the baseline")
    p.add_argument("--store", required=True)
    p.add_argument("run_id")
    p.set_defaults(fn=cmd_bless)

    p = sub.add_parser("status", help="latest metrics vs baseline")
    p.add_argument("--store", required=True)
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("report", help="metric trends over recent runs")
    p.add_argument("--store", required=True)
    p.add_argument("--last", type=int, default=10)
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("verify", help="verify the audit hash chain")
    p.add_argument("--store", required=True)
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("outbox", help="list alerts written")
    p.add_argument("--store", required=True)
    p.set_defaults(fn=cmd_outbox)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
