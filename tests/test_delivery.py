import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ragdrift.delivery import DeliveryError, deliver_outbox, send_webhook


class DeliveryTests(unittest.TestCase):
    def test_untrusted_scheme_rejected_before_network(self):
        with patch('ragdrift.delivery.urllib.request.build_opener') as opener:
            for url in ('http://example.invalid', 'file:///etc/passwd',
                        'https://u:p@example.invalid', 'https://[bad',
                        'https://example.invalid:bad', 'https://example.invalid/#secret'):
                with self.assertRaises(DeliveryError):
                    send_webhook(url, {})
            opener.assert_not_called()

    def test_failed_delivery_retries_and_success_dedups(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'outbox'
            p.mkdir()
            (p / 'a.json').write_text(json.dumps({'metric': 'x', 'delta': -.1}))
            def fail(url, alert):
                raise DeliveryError('test failure')
            self.assertEqual(deliver_outbox(d, 'https://example.invalid', fail)['failed'], ['a.json'])
            sent = []
            def success(url, alert):
                sent.append(alert)
                return {'status': 200}
            self.assertEqual(deliver_outbox(d, 'https://example.invalid', success)['sent'], ['a.json'])
            self.assertEqual(deliver_outbox(d, 'https://example.invalid', success)['sent'], [])
            self.assertEqual(len(sent), 1)
            self.assertTrue((p / 'a.json').exists())

    def test_missing_store_fails_without_send(self):
        with tempfile.TemporaryDirectory() as d:
            sender = MagicMock()
            with self.assertRaises(DeliveryError):
                deliver_outbox(d, 'https://example.invalid', sender)
            sender.assert_not_called()

    def test_bad_receipts_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'outbox').mkdir()
            (p / 'outbox' / 'a.json').write_text('{}')
            sender = MagicMock()
            for text in ('{', '[]'):
                (p / 'delivery_receipts.json').write_text(text)
                with self.assertRaises(DeliveryError):
                    deliver_outbox(d, 'https://example.invalid', sender)
            sender.assert_not_called()

    def test_bad_alert_does_not_block_later_valid_alert(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'outbox'
            p.mkdir()
            (p / 'a.json').write_text('{')
            (p / 'b.json').write_text('{}')
            sender = MagicMock(return_value={'status': 200})
            result = deliver_outbox(d, 'https://example.invalid', sender)
            self.assertEqual(result, {'sent': ['b.json'], 'failed': ['a.json']})
            sender.assert_called_once()

    def test_overlapping_delivery_fails_before_send(self):
        from ragdrift.delivery import _delivery_lock
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'outbox').mkdir()
            (p / 'outbox' / 'a.json').write_text('{}')
            sender = MagicMock()
            with _delivery_lock(p):
                with self.assertRaises(DeliveryError):
                    deliver_outbox(d, 'https://example.invalid', sender)
            sender.assert_not_called()

    def test_receipt_failure_reports_uncertainty(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'outbox'
            p.mkdir()
            (p / 'a.json').write_text('{}')
            sender = MagicMock(return_value={'status': 200})
            with patch('ragdrift.delivery.Path.replace', side_effect=OSError):
                with self.assertRaisesRegex(DeliveryError, 'acknowledged'):
                    deliver_outbox(d, 'https://example.invalid', sender)
            sender.assert_called_once()
            self.assertTrue((p / 'a.json').exists())

    def test_transport_success_and_sanitized_failure(self):
        response = MagicMock()
        response.__enter__.return_value.status = 204
        with patch('ragdrift.delivery.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value = response
            self.assertEqual(send_webhook('https://example.invalid', {})['status'], 204)
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_method(), 'POST')
            self.assertTrue(request.get_header('Idempotency-key'))
            opener.return_value.open.side_effect = OSError('secret-url')
            with self.assertRaises(DeliveryError) as exc:
                send_webhook('https://example.invalid', {})
            self.assertNotIn('secret-url', str(exc.exception))

    def test_cli_delivery_error_has_no_traceback(self):
        from ragdrift.cli import main
        from io import StringIO
        with patch.dict('os.environ', {'RAGDRIFT_WEBHOOK_URL': 'https://[bad'}):
            with patch('sys.stderr', new_callable=StringIO) as stderr:
                self.assertEqual(main(['deliver', '--store', '/no-such-store']), 2)
                self.assertNotIn('Traceback', stderr.getvalue())
