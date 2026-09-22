# Sources

All evaluation logic comes from Charan's own sibling repos — this harness
adapts them, never reimplements them. Sibling SHAs are recorded in every
run's config block.

- **rag-governance-demo** — `https://github.com/ram-polisetti/rag-governance-demo`
  - Eval harness: `src/eval.py` (`run_eval`), 37 cases in `evals/test_set.json`
  - SHA used in development/demo: `c339ae1`
- **rag-redteam** — `https://github.com/ram-polisetti/rag-redteam`
  - Attack battery: `ragredteam/runner.py` (`run_suite`), target `ragredteam/adapters.py` (`RagGovernanceDemoTarget`)
  - SHA used in development/demo: `169e4c8`

No external data sources. No model versions beyond the stub/extractive backends inside the sibling repos.
