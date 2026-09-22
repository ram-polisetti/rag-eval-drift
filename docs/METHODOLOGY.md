# Methodology

## Run cycle

Each `ragdrift run` executes, in order:

1. **Adapters** — `GovDemoAdapter` imports `rag-governance-demo`'s `src/eval.py` and calls its real `run_eval()` (37 cases: groundedness, citation correctness, refusal behavior, cross-domain isolation, red-team attack cases). `RedteamAdapter` imports `rag-redteam`'s runner and runs its real attack battery (7 families, 49 cases) against the demo target in-process. Each adapter returns a flat metrics dict (rates in [0,1]), counts, and the list of regressed cases/families.
2. **Store** — the full run record (metrics, counts, config incl. sibling git SHAs, harness version, notes) is appended to `runs.jsonl`.
3. **Baseline** — the first run auto-pins as baseline. Later runs compare against it. `ragdrift bless <run-id>` re-pins manually (e.g. after an intentional improvement) and resets alert dedup.
4. **Drift detection** — see `docs/DRIFT_DETECTION.md`.
5. **Alerting** — one JSON file per drift finding in `outbox/`, deduplicated per (metric, rule) until recovery. Improvements never page.
6. **Audit** — run, baseline, and alert events appended to a SHA-256 hash-chained `audit.jsonl`.

## Evidence

Every drift finding carries evidence: the list of eval cases (or attack families) that regressed *between the baseline and current run*, plus regressed-case counts for both runs. An alert names exactly what moved, by how much, and which cases broke — enough to start debugging without re-running anything.

## What "baseline" means

The baseline is a blessed known-good state, not a rolling average. Rolling baselines hide slow decay (the thing the trend rule exists to catch). When the app intentionally changes (new corpus version, new model), bless a new baseline after verifying the change is good.
