"""rag-eval-drift: scheduled RAG evaluation-drift harness.

Re-runs Charan's RAG eval suites on a cadence and flags quality decay
when model, prompt, or corpus changes degrade the governed RAG app.
"""

__version__ = "0.1.0"
