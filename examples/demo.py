"""End-to-end demo: baseline a healthy RAG app, then catch a real regression.

Stage 1: run the drift harness against the clean rag-governance-demo
         checkout -> baseline pinned (first run).
Stage 2: run it against a degraded copy (two corpus documents deleted,
         simulating a bad corpus update) -> drift flagged with evidence,
         alert written to the outbox.

Usage: python3 examples/demo.py <demo-path> <redteam-path>
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sh(*args):
    r = subprocess.run(args, capture_output=True, text=True, timeout=600)
    print(r.stdout, end="")
    if r.returncode not in (0, 1):
        print(r.stderr[-2000:], file=sys.stderr)
        raise SystemExit(f"command failed: {args[0]} (exit {r.returncode})")
    return r.returncode


def main():
    demo_path, redteam_path = sys.argv[1], sys.argv[2]
    store = Path("/tmp/ragdrift-demo-store")
    if store.exists():
        shutil.rmtree(store)

    env = {"PYTHONPATH": str(ROOT / "src")}
    import os
    full_env = dict(os.environ, **env)

    def run_cli(*a):
        r = subprocess.run([sys.executable, "-m", "ragdrift", *a],
                           capture_output=True, text=True, timeout=600,
                           env=full_env, cwd=str(ROOT))
        print(r.stdout, end="")
        if r.returncode not in (0, 1):
            print(r.stderr[-2000:], file=sys.stderr)
            raise SystemExit("ragdrift failed")
        return r.returncode

    print("=== Stage 1: baseline the healthy app ===")
    run_cli("run", "--store", str(store), "--demo-path", demo_path,
            "--redteam-path", redteam_path, "--notes", "demo baseline")

    degraded = Path("/tmp/ragdrift-degraded-demo")
    if degraded.exists():
        shutil.rmtree(degraded)
    shutil.copytree(demo_path, degraded)
    # Genuine regression: a bad corpus update deletes two policy documents.
    (degraded / "corpus" / "hr-hiring" / "referral-policy.md").unlink()
    (degraded / "corpus" / "supply-chain" / "cold-chain-policy.md").unlink()
    print("\n=== Stage 2: corpus regression introduced "
          "(referral-policy.md + cold-chain-policy.md deleted) ===")
    code = run_cli("run", "--store", str(store), "--demo-path", str(degraded),
                   "--redteam-path", redteam_path,
                   "--notes", "demo degraded run")
    assert code == 1, "expected drift to be detected (exit 1)"

    print("\n=== Alerts written ===")
    run_cli("outbox", "--store", str(store))
    print("\n=== Trend report ===")
    run_cli("report", "--store", str(store), "--last", "5")
    print("\n=== Audit chain ===")
    run_cli("verify", "--store", str(store))
    print("\nDEMO OK: drift detected, alerted, audited.")


if __name__ == "__main__":
    main()
