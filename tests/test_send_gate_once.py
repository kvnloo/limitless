"""send_gate.decide(once_key=...): one message per event, whichever sender gets there first.

Synthetic fixtures only. NOW is an arbitrary epoch; only differences between times matter.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import send_gate as g  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0
KEY = "wake_brief:1999990000"


def decide(title="Wake-up brief", body="b", cls="decision", sent=(), asleep=False, once_key=None):
    return g.decide("limitless", title, body, cls, NOW, list(sent), asleep, once_key=once_key)


class OnceKey(unittest.TestCase):
    def test_other_text_same_key_within_12h_is_dropped(self):
        sent = [{"t": NOW - H, "k": g.key("Wake-up brief", "older words"), "once": KEY}]
        self.assertEqual(decide(body="newer words", sent=sent, once_key=KEY), "drop")

    def test_the_drop_reason_is_plain_words(self):
        self.assertEqual(g.ONCE_DROP, "already sent for this event")

    def test_other_key_is_sent(self):
        sent = [{"t": NOW - H, "k": g.key("Wake-up brief", "older words"), "once": KEY}]
        self.assertEqual(decide(body="newer words", sent=sent, once_key="wake_brief:1999999999"), "send")

    def test_same_key_after_12h_is_sent(self):
        sent = [{"t": NOW - 13 * H, "k": g.key("Wake-up brief", "older words"), "once": KEY}]
        self.assertEqual(decide(body="newer words", sent=sent, once_key=KEY), "send")

    def test_first_message_for_a_key_is_sent(self):
        self.assertEqual(decide(once_key=KEY), "send")

    def test_rows_without_a_key_never_claim_one(self):
        sent = [{"t": NOW - H, "k": g.key("Wake-up brief", "older words")}]
        self.assertEqual(decide(body="newer words", sent=sent, once_key=KEY), "send")

    def test_a_claimed_key_drops_before_sleep_mode_holds_it(self):
        # A held message is replayed later; one already sent for this event must not be.
        sent = [{"t": NOW - H, "k": "x", "once": KEY}]
        self.assertEqual(decide(sent=sent, asleep=True, once_key=KEY), "drop")

    def test_same_text_other_key_is_still_a_duplicate(self):
        sent = [{"t": NOW - H, "k": g.key("Wake-up brief", "b"), "once": KEY}]
        self.assertEqual(decide(sent=sent, once_key="wake_brief:1999999999"), "duplicate")

    def test_without_a_key_a_claimed_key_changes_nothing(self):
        sent = [{"t": NOW - H, "k": g.key("Wake-up brief", "older words"), "once": KEY}]
        self.assertEqual(decide(body="newer words", sent=sent), "send")

    def test_report_class_stays_log_only(self):
        sent = [{"t": NOW - H, "k": "x", "once": KEY}]
        self.assertEqual(decide(title="Note", cls="report", sent=sent, once_key=KEY), "log")

    def test_once_sent_helper(self):
        sent = [{"t": NOW - H, "k": "x", "once": KEY}, {"t": NOW - H, "k": "y"}, "junk"]
        self.assertTrue(g.once_sent(sent, KEY, NOW))
        self.assertFalse(g.once_sent(sent, "miq:1", NOW))
        self.assertFalse(g.once_sent(sent, None, NOW))
        self.assertFalse(g.once_sent(sent, KEY, NOW + 12 * H))


if __name__ == "__main__":
    unittest.main()
