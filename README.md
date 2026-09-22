# rag-eval-drift

A scheduled service that re-runs Charan's RAG evaluation suites on a cadence and detects when model, prompt, or corpus changes degrade quality. The "after" half of RAG governance: `rag-governance-demo`'s eval harness checks a RAG app before it ships; this watches eval quality decay over time.

Built by an operator, for operators.

## What it does

- **Eval-suite adapters** run the *real* sibling tools — `rag-governance-demo`'s eval harness (groundedness, citations, refusals, red-team cases) and `rag-redteam`'s attack battery (attack-pass rate) — never reimplementations. Sibling SHAs are recorded in every run.
- **Scheduler-friendly CLI**: `ragdrift run` does one full cycle (eval → drift detect → alert → audit). Run it from cron daily/weekly.
- **Drift detection**: threshold rule (metric falls ≥ 5 points vs pinned baseline) + trend rule (3 consecutive declines), with a noise floor. See `docs/DRIFT_DETECTION.md`.
- **Alerting**: one JSON alert per drift finding in `outbox/`, deduplicated (no double-paging). Webhook/SMTP are documented stubs.
- **Audit**: every run, baseline pin, and alert appended to a hash-chained JSONL log with tamper detection.
- **Status UI**: `ragdrift status` (latest vs baseline), `ragdrift report` (trends).

## Quickstart (stdlib only)

```bash
# one full cycle; first run auto-pins the baseline
PYTHONPATH=src python3 -m ragdrift run \
  --store ./state \
  --demo-path /path/to/rag-governance-demo \
  --redteam-path /path/to/rag-redteam

# latest metrics vs baseline
PYTHONPATH=src python3 -m ragdrift status --store ./state

# trend table
PYTHONPATH=src python3 -m ragdrift report --store ./state

# verify the audit chain
PYTHONPATH=src python3 -m ragdrift verify --store ./state

# re-pin the baseline to a known-good run
PYTHONPATH=src python3 -m ragdrift bless --store ./state <run-id>
```

Exit codes for `run`: 0 = no drift, 1 = drift detected (alerts written), 2 = error. Cron-friendly.

Config file (JSON, `--config`): `threshold`, `trend_window`, `trend_epsilon`, `redteam_families`. See `config.example.json`.

## Demo

`python3 examples/demo.py <demo-path> <redteam-path>` — baselines the healthy app, then introduces a genuine corpus regression (two policy documents deleted) and shows the harness flagging exactly the degraded metrics with evidence, writing alerts, and keeping the audit chain intact.

## Docs

- `docs/METHODOLOGY.md` — how runs, baselines, and evidence work
- `docs/DRIFT_DETECTION.md` — the two rules, the noise floor, and why this is not a significance test
- `docs/SOURCES.md` — sibling repos and exact SHAs
- `docs/LIMITATIONS.md` — what this does not catch
- `CHANGELOG.md`

## License

Apache-2.0.
