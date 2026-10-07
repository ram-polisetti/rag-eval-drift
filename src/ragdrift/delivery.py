"""Explicit opt-in webhook delivery with receipts and retryable failures.

Nothing is transmitted unless a caller supplies a destination. The caller
owns consent, destination validation, and any private content in the alert.
"""
import hashlib
import json
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


class DeliveryError(Exception):
    pass


def _validate_url(url):
    try:
        parts = urlsplit(url)
        valid = (parts.scheme == 'https' and parts.hostname
                 and not parts.username and not parts.password
                 and not parts.fragment and parts.port != 0)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise DeliveryError('webhook requires a valid HTTPS URL without embedded credentials or fragments')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # never redirect private alert payloads to another host


def send_webhook(url, alert, timeout=10):
    _validate_url(url)
    try:
        payload = json.dumps(alert, sort_keys=True).encode()
        key = hashlib.sha256(payload).hexdigest()
        request = urllib.request.Request(url, data=payload, method='POST', headers={
            'Content-Type': 'application/json', 'Idempotency-Key': key})
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout) as response:
            if not 200 <= response.status < 300:
                raise DeliveryError('webhook returned a non-success status')
            return {'status': response.status, 'payload_sha256': key}
    except Exception:
        # Do not echo a URL or response body that may contain a secret.
        raise DeliveryError('webhook delivery failed; alert retained for retry') from None


@contextmanager
def _delivery_lock(root):
    # Fail closed on platforms lacking flock. Keep the inode after release so
    # waiting processes never lock an obsolete/unlinked file.
    try:
        import fcntl
        with (root / '.delivery.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    except (ImportError, OSError):
        raise DeliveryError('delivery lock unavailable or another delivery is running; nothing further sent') from None


def deliver_outbox(store_dir, url, sender=send_webhook):
    """Retry unsent alerts, record success only after acknowledgement.

    An uncertain network failure may have reached the receiver. The stable
    idempotency key supports receiver-side dedup, not an exactly-once claim.
    A local process lock serializes delivery; it is not a distributed lock.
    """
    _validate_url(url)
    root = Path(store_dir)
    outbox = root / 'outbox'
    if not root.is_dir() or not outbox.is_dir():
        raise DeliveryError('store and outbox directories must exist; nothing sent')
    with _delivery_lock(root):
        receipts_path = root / 'delivery_receipts.json'
        try:
            receipts = json.loads(receipts_path.read_text()) if receipts_path.exists() else {}
            if not isinstance(receipts, dict):
                raise ValueError('invalid receipts')
        except (ValueError, OSError):
            raise DeliveryError('receipt store unreadable or invalid; nothing sent') from None
        destination = hashlib.sha256(url.encode()).hexdigest()
        sent, failed = [], []
        for path in sorted(outbox.glob('*.json')):
            try:
                alert = json.loads(path.read_text())
                if not isinstance(alert, dict):
                    raise ValueError('invalid alert')
            except (ValueError, OSError):
                failed.append(path.name)
                continue
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
            try:
                temp.write_text(json.dumps(receipts, indent=2, sort_keys=True))
                temp.replace(receipts_path)
            except (OSError, TypeError, ValueError):
                raise DeliveryError('delivery acknowledged but receipt could not be saved; retry may resend') from None
            sent.append(path.name)
        return {'sent': sent, 'failed': failed}
