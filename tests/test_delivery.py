import json
import tempfile
import unittest
from pathlib import Path
from ragdrift.delivery import DeliveryError, deliver_outbox, send_webhook


class DeliveryTests(unittest.TestCase):
    def test_untrusted_scheme_rejected_before_network(self):
        for url in ('http://example.invalid', 'file:///etc/passwd', 'https://u:p@example.invalid'):
            with self.assertRaises(DeliveryError):
                send_webhook(url, {})

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
