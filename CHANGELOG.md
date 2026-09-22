# Changelog

## 0.1.0 — 2026-09-22

- Initial release.
- `GovDemoAdapter` (real rag-governance-demo eval harness) + `RedteamAdapter` (real rag-redteam attack battery).
- Drift rules: threshold (5pt default) + trend (3 consecutive declines), noise floor, improvements never page.
- Alert outbox with per-(metric, rule) dedup and recovery clearing.
- Hash-chained JSONL audit log (`run`, `baseline`, `alert` events) with `verify`.
- CLI: `run` (exit 0/1/2, cron-compatible), `bless`, `status`, `report`, `verify`, `outbox`.
- 16 tests green; end-to-end demo catches a genuine corpus regression with evidence.
