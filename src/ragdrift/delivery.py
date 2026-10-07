"""Explicit opt-in webhook delivery with receipts and retryable failures.

Nothing is transmitted unless a caller supplies a destination. The caller
owns consent, destination validation, and any private content in the alert.
"""
import hashlib
import json
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


class DeliveryError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # never redirect private alert payloads to another host


def send_webhook(url, alert, timeout=10):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise DeliveryError('webhook requires an HTTPS URL without embedded credentials')
    payload = json.dumps(alert, sort_keys=True).encode()
    key = hashlib.sha256(payload).hexdigest()
    request = urllib.request.Request(url, data=payload, method='POST', headers={
        'Content-Type': 'application/json', 'Idempotency-Key': key})
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout) as response:
            if not 200 <= response.status < 300:
                raise DeliveryError('webhook returned a non-success status')
            return {'status': response.status, 'payload_sha256': key}
    except Exception as exc:
        # Do not echo a URL or response body that may contain a secret.
        raise DeliveryError('webhook delivery failed; alert retained for retry') from exc


def deliver_outbox(store_dir, url, sender=send_webhook):
    """Retry unsent alerts, record success only after acknowledgement.

    An uncertain network failure may have reached the receiver. The stable
    idempotency key supports receiver-side dedup, not an exactly-once claim.
    """
    root = Path(store_dir)
    receipts_path = root / 'delivery_receipts.json'
    receipts = json.loads(receipts_path.read_text()) if receipts_path.exists() else {}
    destination = hashlib.sha256(url.encode()).hexdigest()
    sent, failed = [], []
    for path in sorted((root / 'outbox').glob('*.json')):
        alert = json.loads(path.read_text())
        key = hashlib.sha256(json.dumps(alert, sort_keys=True).encode()).hexdigest()
        receipt_key = destination + ':' + key
        if receipt_key in receipts:
            continue
        try:
            receipt = sender(url, alert)
        except DeliveryError:
            failed.append(path.name)
            continue
        receipts[receipt_key] = receipt
        temp = receipts_path.with_suffix('.tmp')
        temp.write_text(json.dumps(receipts, indent=2, sort_keys=True))
        temp.replace(receipts_path)
        sent.append(path.name)
    return {'sent': sent, 'failed': failed}
