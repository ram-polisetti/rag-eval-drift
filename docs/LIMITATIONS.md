# Limitations

1. **Rule-based, not statistical.** Drift rules are transparent thresholds, not significance tests (see `docs/DRIFT_DETECTION.md`). Small case counts mean single-case flips are visible; the 5-point default threshold absorbs most of that.
2. **Only what the suites measure.** If the eval suite doesn't cover a quality dimension, this harness can't see it decay. Eval coverage is the real ceiling.
3. **Stub backends.** The sibling demo apps use extractive/stub backends; drift signals here reflect retrieval/corpus/gate changes, not LLM behavior drift. Against a live LLM-backed RAG app, expect noisier metrics — raise `trend_epsilon` and consider longer trend windows.
4. **Baseline discipline required.** The harness trusts the pinned baseline. A bad baseline (pinned during a degraded state) makes everything look fine. Bless deliberately.
5. **Alert delivery is opt-in.** Alerts land as JSON files in `outbox/`. `ragdrift deliver` can send to an operator-approved HTTPS webhook; SMTP remains a stub. No automatic sends, production destination or durable schedule is configured. Receipts are local and retries need receiver-side idempotency. Delivery locking requires local POSIX `flock`, not a shared/network filesystem. See `DELIVERY.md`.
6. **No multi-run case pairing.** Only regressed-case lists are stored per run, so paired statistical tests across runs aren't possible yet.
7. **Adapter failures.** If one adapter fails, the run proceeds with the other and warns; if both fail, the run exits 2 and nothing is stored. A failed adapter is not drift — check stderr.
8. **Corpus-path coupling.** Adapters point at sibling checkouts on disk; moving or updating a sibling without re-blessing can produce confusing diffs. The sibling SHAs in each run record are there for exactly this forensics.
9. **Not a security monitor.** This watches eval quality over time; it does not detect live attacks or data exfiltration in production.
10. **Single-machine state.** `runs.jsonl`, `state.json`, and `audit.jsonl` live in `--store`; back it up like any other operational state.
