"""The sender_changed event (jobs.sender_changed_verdict, push_sender.reply_at): push-sender.json's ``at`` is newer
than the last confirmation the mark settled. Pure verdicts over synthetic epochs and a temp state dir; never a
clock time, nothing sent.""" 
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, push_sender  # noqa: E402

NOW = 1894708800.0   # 2030-01-15T12:00:00Z
H = 3600


class Event(unittest.TestCase):
    def v(self, reply_at, settled_at=None, now=NOW, mode=jobs.SENDER_CONFIRM_WRITE):
        return jobs.sender_changed_verdict(mode, reply_at, settled_at, now)

    def test_the_event_is_in_the_event_list_and_the_spec_wakes_on_it(self):
        self.assertIn("sender_changed", jobs.EVENTS)
        spec = jobs.SENDER_CONFIRM
        self.assertEqual((spec.name, spec.trigger_event, spec.expires, spec.send_title),
                         ("sender_confirm", "sender_changed", "sender_changed", "Pushes"))
        self.assertNotIn(spec.name, jobs.SPECS)

    def test_a_reply_newer_than_the_last_confirmation_is_due(self):
        v = self.v(NOW - 60)
        self.assertEqual((v.action, v.trigger_at), (jobs.DELIVER, NOW - 60))
        self.assertEqual(v.reason, jobs.SENDER_CHANGED)
        v = self.v(NOW - 60, settled_at=NOW - 2 * H)
        self.assertEqual(v.action, jobs.DELIVER)

    def test_the_same_or_an_older_reply_is_a_drop(self):
        self.assertEqual(self.v(NOW - 60, settled_at=NOW - 60).action, jobs.DROP)
        self.assertEqual(self.v(NOW - H, settled_at=NOW - 60).action, jobs.DROP)

    def test_no_reply_a_future_reply_or_off_is_not_triggered(self):
        self.assertEqual(self.v(None).action, jobs.NOT_TRIGGERED)
        self.assertEqual(self.v(NOW + 60).action, jobs.NOT_TRIGGERED)
        off = self.v(NOW - 60, mode=jobs.SENDER_CONFIRM_OFF)
        self.assertEqual((off.action, off.reason), (jobs.NOT_TRIGGERED, jobs.SENDER_CONFIRM_IS_OFF))

    def test_a_late_confirmation_is_noise(self):
        v = self.v(NOW - jobs.SENDER_CONFIRM_STALE_S - 60)
        self.assertEqual(v.action, jobs.DROP)
        self.assertIn("too late", v.reason)

    def test_reasons_are_words_never_a_clock_or_a_digit(self):
        for v in (self.v(None), self.v(NOW - 60), self.v(NOW - 60, NOW - 60), self.v(NOW + 60),
                  self.v(NOW - jobs.SENDER_CONFIRM_STALE_S - 60)):
            self.assertFalse(any(c.isdigit() for c in v.reason), v.reason)

    def test_mode_is_off_by_default_and_for_anything_else(self):
        self.assertEqual(jobs.sender_confirm_mode({}), jobs.SENDER_CONFIRM_OFF)
        self.assertEqual(jobs.sender_confirm_mode({"sender_confirm": "loud"}), jobs.SENDER_CONFIRM_OFF)
        self.assertEqual(jobs.sender_confirm_mode({"sender_confirm": " Write "}), jobs.SENDER_CONFIRM_WRITE)
        self.assertEqual(jobs.sender_confirm_mode({"sender_confirm": "dry_run"}), jobs.SENDER_CONFIRM_DRY_RUN)


class ReplyAt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, obj):
        (self.st / push_sender.REPLY_FILE).write_text(obj if isinstance(obj, str) else json.dumps(obj))

    def test_the_reply_files_epoch_when_it_names_a_profile(self):
        self.put({"profile": "backup-bot", "at": NOW - 60})
        self.assertEqual(push_sender.reply_at(self.st), NOW - 60)

    def test_none_for_anything_kevin_push_would_not_use(self):
        self.assertIsNone(push_sender.reply_at(self.st))            # no file
        self.assertIsNone(push_sender.reply_at(None))
        for bad in ("{", [], {"at": NOW}, {"profile": "Bad Name!", "at": NOW}, {"profile": "ok", "at": "soon"},
                    {"profile": "ok", "at": True}, {"profile": "ok"}, {"profile": "ok", "at": float("nan")}):
            self.put(bad)
            self.assertIsNone(push_sender.reply_at(self.st), bad)


if __name__ == "__main__":
    unittest.main()
