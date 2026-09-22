"""Alerting: local outbox + dedup. Webhook/SMTP are documented stubs."""

import json
import time
from pathlib import Path


def _utcnow():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Alerter:
    """Writes one JSON alert per drift finding into outbox/.

    Dedup: a finding for the same (metric, rule) is not re-alerted while
    the metric stays below baseline. Recovery (metric back within half
    the threshold of baseline) clears the dedup key.
    """

    def __init__(self, store_dir):
        self.dir = Path(store_dir) / "outbox"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path = Path(store_dir) / "alert_state.json"

    def _state(self):
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        return {"active": {}}

    def _save(self, state):
        self.state_path.write_text(json.dumps(state, indent=2, sort_keys=True))

    def _key(self, finding):
        return f"{finding['metric']}:{finding['rule']}"

    def alert(self, run_id, findings, threshold):
        """Returns the list of alerts actually written (after dedup)."""
        state = self._state()
        active = state.setdefault("active", {})
        written = []
        for f in findings:
            if f["rule"] == "improvement":
                continue  # never page on improvements
            key = self._key(f)
            if key in active:
                continue  # already paged for this drift
            alert = {
                "alerted_at": _utcnow(), "run_id": run_id,
                "severity": "drift",
                "metric": f["metric"], "rule": f["rule"],
                "baseline": f["baseline"], "current": f["current"],
                "delta": f["delta"],
                "evidence": f["evidence"],
                "message": (f"DRIFT: {f['metric']} fell "
                            f"{f['baseline']:.1%} → {f['current']:.1%} "
                            f"(rule: {f['rule']})"),
            }
            fname = f"{alert['alerted_at'].replace(':', '')}-{f['metric'].replace('.', '_')}.json"
            (self.dir / fname).write_text(json.dumps(alert, indent=2, sort_keys=True))
            active[key] = {"run_id": run_id, "alerted_at": alert["alerted_at"]}
            written.append(alert)
        self._save(state)
        return written

    def clear_recovered(self, findings, current_metrics, baseline_metrics, threshold):
        """Drop dedup keys for metrics that recovered near baseline."""
        state = self._state()
        active = state.get("active", {})
        flagged = {self._key(f) for f in findings if f["rule"] != "improvement"}
        for key in list(active):
            metric = key.rsplit(":", 1)[0]
            if key in flagged:
                continue
            cur = current_metrics.get(metric)
            base = baseline_metrics.get(metric)
            if cur is not None and base is not None and cur >= base - threshold / 2:
                del active[key]
        self._save(state)

    def outbox(self):
        return sorted(p.name for p in self.dir.glob("*.json"))


def send_webhook(url, alert):
    """Stub: POST the alert JSON to a webhook URL.

    Not wired to run automatically — set RAGDRIFT_WEBHOOK_URL and call from
    your own scheduler. Documented here so the integration point is explicit.
    """
    raise NotImplementedError(
        "webhook delivery is a stub: POST alert JSON to the given URL "
        "from your scheduler (see docs/LIMITATIONS.md)")


def send_smtp(host, alert, **kwargs):
    """Stub: email the alert. No credentials are stored or used by default."""
    raise NotImplementedError(
        "SMTP delivery is a stub: no credentials configured "
        "(see docs/LIMITATIONS.md)")
