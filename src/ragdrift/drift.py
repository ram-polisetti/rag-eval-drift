"""Drift detection: rule-based comparison of a run against a pinned baseline.

Two rules, both deliberately simple and documented in docs/DRIFT_DETECTION.md:

1. THRESHOLD — a metric falls >= ``threshold`` (default 0.05, i.e. 5 points)
   below its baseline value → drift. Upward moves of the same size are
   reported as improvements, never alerts.

2. TREND — the last ``trend_window`` (default 3) runs each declined by at
   least ``trend_epsilon`` (default 0.005) versus the previous run →
   drift, even when the total drop is still under the threshold.

Noise handling: changes smaller than ``trend_epsilon`` are ignored
entirely. With ~37 eval cases, a single case flip moves a rate by ~2.7
points, so the default 5-point threshold means "at least two cases
regressed" — a deliberate bias toward signal over noise. This is NOT a
statistical significance test (see docs/DRIFT_DETECTION.md for why).
"""

DEFAULT_THRESHOLD = 0.05
DEFAULT_TREND_WINDOW = 3
DEFAULT_TREND_EPSILON = 0.005

# Metrics where DOWN is bad. Anything not listed is treated as down-is-bad
# too (all current metrics are pass rates), listed here for clarity.
DOWN_IS_BAD = (
    "eval.overall_pass_rate", "eval.groundedness_rate",
    "eval.refusal_handling_rate", "eval.redteam_sub_rate",
    "redteam.attack_pass_rate",
)


def _flat_metrics(run):
    out = {}
    for ad in run["adapters"].values():
        out.update(ad["metrics"])
    return out


def detect(baseline_run, current_run, history_runs=None,
           threshold=DEFAULT_THRESHOLD,
           trend_window=DEFAULT_TREND_WINDOW,
           trend_epsilon=DEFAULT_TREND_EPSILON):
    """Return a list of drift findings for ``current_run``.

    Each finding: {metric, rule, baseline, current, delta, direction,
    evidence}. ``history_runs`` are runs between baseline and current
    (oldest→newest) for the trend rule.
    """
    findings = []
    base = _flat_metrics(baseline_run)
    cur = _flat_metrics(current_run)
    for metric, cur_v in sorted(cur.items()):
        base_v = base.get(metric)
        if base_v is None:
            continue  # new metric: nothing to compare against
        delta = cur_v - base_v
        if abs(delta) < trend_epsilon:
            continue  # noise floor
        if delta <= -threshold:
            findings.append({
                "metric": metric, "rule": "threshold",
                "baseline": round(base_v, 4), "current": round(cur_v, 4),
                "delta": round(delta, 4), "direction": "down",
                "evidence": _evidence(baseline_run, current_run, metric),
            })
        elif delta >= threshold:
            findings.append({
                "metric": metric, "rule": "improvement",
                "baseline": round(base_v, 4), "current": round(cur_v, 4),
                "delta": round(delta, 4), "direction": "up",
                "evidence": _evidence(baseline_run, current_run, metric),
            })
    # Trend rule: N consecutive declines >= epsilon, even under threshold.
    hist = list(history_runs or [])
    seq = hist + [current_run]
    if len(seq) >= trend_window:
        window = seq[-trend_window:]
        for metric in sorted(cur):
            vals = [_flat_metrics(r).get(metric) for r in window]
            if any(v is None for v in vals):
                continue
            diffs = [b - a for a, b in zip(vals, vals[1:])]
            if all(d <= -trend_epsilon for d in diffs):
                if not any(f["metric"] == metric and f["rule"] == "threshold"
                           for f in findings):
                    findings.append({
                        "metric": metric, "rule": "trend",
                        "baseline": round(vals[0], 4),
                        "current": round(vals[-1], 4),
                        "delta": round(vals[-1] - vals[0], 4),
                        "direction": "down",
                        "evidence": {
                            "window": [round(v, 4) for v in vals],
                            "note": f"{trend_window} consecutive declines",
                        },
                    })
    return findings


def _evidence(baseline_run, current_run, metric):
    """Which eval cases regressed between baseline and current run."""
    base_reg = set()
    cur_reg = set()
    for run, s in ((baseline_run, base_reg), (current_run, cur_reg)):
        for ad in run["adapters"].values():
            s.update(ad.get("regressed_cases", []))
    new = sorted(cur_reg - base_reg)
    return {
        "newly_regressed": new[:20],
        "baseline_regressed_count": len(base_reg),
        "current_regressed_count": len(cur_reg),
    }
