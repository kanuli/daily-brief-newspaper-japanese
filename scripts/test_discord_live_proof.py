"""Offline notification proof tests; webhook and file reads are mocked."""
import contextlib
import hashlib
import io
import json
import unittest
from unittest.mock import patch

import notify_discord as notify


class ProofTests(unittest.TestCase):
    def setUp(self):
        self.live = {"lastUpdated": "2026-10-10T11:44:00+08:00",
                     "items": [{"id": "new", "title": "新しい記事", "summary": "検証済み"}]}

    def run_notification(self, live, failure=None):
        stream = io.StringIO()
        with patch.object(notify, "load", return_value=live), patch.object(notify, "post", side_effect=failure) as post, contextlib.redirect_stdout(stream):
            if failure:
                with self.assertRaises(type(failure)):
                    notify.send_published_live()
            else:
                notify.send_published_live()
        return stream.getvalue(), post.call_count

    def test_success_proves_exact_snapshot_after_webhook(self):
        output, count = self.run_notification(self.live)
        digest = hashlib.sha256(json.dumps(self.live, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertIn("DISCORD_LIVE_PUBLICATION_PROOF " + digest, output)
        self.assertEqual(count, 1)

    def test_failure_never_proves_delivery(self):
        output, count = self.run_notification(self.live, TimeoutError("synthetic"))
        self.assertNotIn("DISCORD_LIVE_PUBLICATION_PROOF", output)
        self.assertEqual(count, 1)

    def test_filtered_corrupt_story_cannot_attest_entire_snapshot(self):
        self.live["items"].append({"id": "bad", "title": "Error 500 (Server Error)"})
        output, count = self.run_notification(self.live)
        self.assertEqual(count, 1)
        self.assertNotIn("DISCORD_LIVE_PUBLICATION_PROOF", output)

    def test_no_safe_items_no_send_or_proof(self):
        self.live["items"] = []
        output, count = self.run_notification(self.live)
        self.assertEqual(count, 0)
        self.assertNotIn("DISCORD_LIVE_PUBLICATION_PROOF", output)


if __name__ == "__main__":
    unittest.main()
