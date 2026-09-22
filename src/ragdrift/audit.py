"""Hash-chained JSONL audit log: every run, baseline pin, and alert."""

import hashlib
import json
import time
from pathlib import Path


def _utcnow():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _hash(entry):
    return hashlib.sha256(
        json.dumps(entry, sort_keys=True).encode()).hexdigest()


class AuditLog:
    def __init__(self, store_dir):
        self.path = Path(store_dir) / "audit.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash(self):
        if not self.path.exists():
            return "GENESIS"
        last = None
        for line in self.path.read_text().splitlines():
            if line.strip():
                last = line
        if not last:
            return "GENESIS"
        return json.loads(last)["hash"]

    def append(self, kind, payload):
        prev = self._last_hash()
        entry = {"ts": _utcnow(), "kind": kind, "payload": payload,
                 "prev": prev}
        entry["hash"] = _hash({k: entry[k] for k in ("ts", "kind", "payload", "prev")})
        with self.path.open("a") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def verify(self):
        """Returns (ok, message)."""
        if not self.path.exists():
            return True, "no audit log yet"
        prev = "GENESIS"
        for i, line in enumerate(self.path.read_text().splitlines()):
            if not line.strip():
                continue
            e = json.loads(line)
            if e["prev"] != prev:
                return False, f"chain broken at record {i}"
            want = _hash({k: e[k] for k in ("ts", "kind", "payload", "prev")})
            if e["hash"] != want:
                return False, f"tamper detected at record {i}"
            prev = e["hash"]
        return True, "chain intact"
