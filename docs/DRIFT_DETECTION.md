# Drift detection

Two deliberately simple rules. Simple beats clever here: the operator must be able to explain every alert.

## Rule 1 — Threshold

A metric falls at least `threshold` (default 0.05 = 5 points) below its baseline value → drift.

Calibration: the gov-demo suite has 37 cases, so one case flip moves a rate by ~2.7 points. A 5-point threshold means "at least two eval cases regressed" (or one red-team family moved materially). This biases toward signal over noise.

Upward moves of the same size are reported as `improvement` findings — visible in output, never paged.

## Rule 2 — Trend

The last `trend_window` (default 3) runs each declined by at least `trend_epsilon` (default 0.005) versus the previous run → drift, even if the total drop is still under the threshold. Catches slow rot that never trips a single big threshold.

A single uptick breaks the streak (no alert on a bounce). If the threshold rule already fired for a metric, the trend rule does not double-report it.

## Noise floor

Changes smaller than `trend_epsilon` are ignored entirely. Metrics with no baseline value (newly added) are skipped, not flagged.

## What this is NOT

This is not a statistical significance test. With 37 eval cases and 49 attack cases, per-run counts are small; a proper test (e.g. McNemar's on paired case outcomes) would be the next step for high-stakes use, but it would also need the paired per-case outcomes stored across runs — currently only regressed-case lists are stored. The rules here are transparent, deterministic, and documented; the limitation is explicit in `docs/LIMITATIONS.md`.

## Tuning

`--config` JSON: `threshold`, `trend_window`, `trend_epsilon`, `redteam_families` (subset of attack families to run, e.g. for a fast daily check vs a full weekly battery).
