"""send_gate with quiet (drop, never hold or queue) and the one "why now" line. Synthetic only; nothing sends."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import send_gate as g  # noqa: E402

NOW = 2_000_000_000.0
HELD = (True, "quiet: off until you reply on")
FREE = (False, "on: pushes go through the send gate")


def decide(tag="x", title="T", body="b", cls="decision", sent=(), asleep=False, quiet=None, once=None):
    return g.decide(tag, title, body, cls, NOW, list(sent), asleep, once_key=once, quiet=quiet)


class QuietDrops(unittest.TestCase):
    def test_a_decision_is_dropped(self):
        self.assertEqual(decide(quiet=HELD), "drop")

    def test_critical_is_dropped_too_there_is_no_urgent_override(self):
        self.assertEqual(decide(cls="critical", quiet=HELD), "drop")

    def test_the_wake_brief_is_dropped(self):
        self.assertEqual(decide(tag="limitless", title="Wake-up brief", cls="digest", quiet=HELD), "drop")

    def test_back_from_nap_is_dropped(self):
        self.assertEqual(decide(tag="limitless", title="Back from nap", quiet=HELD), "drop")

    def test_asleep_and_quiet_is_dropped_not_held(self):
        self.assertEqual(decide(asleep=True, quiet=HELD), "drop")

    def test_not_held_is_as_before(self):
        self.assertEqual(decide(quiet=FREE), "send")
        self.assertEqual(decide(quiet=None), "send")
        self.assertEqual(decide(asleep=True, quiet=FREE), "hold")

    def test_log_only_and_fold_stay_as_they_are(self):
        self.assertEqual(decide(cls="report", quiet=HELD), "log")
        self.assertEqual(decide(tag="asks", quiet=HELD), "fold")

    def test_quiet_reason(self):
        self.assertEqual(g.quiet_reason(HELD), "quiet: off until you reply on")
        self.assertIsNone(g.quiet_reason(FREE))
        self.assertIsNone(g.quiet_reason(None))


class QuietRows(unittest.TestCase):
    """A quiet drop claims its event key (so a later retry for that event is dropped, not queued) and never
    counts as a send for the daily cap or the dedupe."""

    def test_quiet_row_shape(self):
        self.assertEqual(g.quiet_row(NOW, "wake_brief:1"), {"t": NOW, "once": "wake_brief:1", "quiet": True})

    def test_a_quiet_row_claims_its_key(self):
        self.assertTrue(g.once_sent([g.quiet_row(NOW - 60, "k1")], "k1", NOW))
        self.assertEqual(decide(once="k1", sent=[g.quiet_row(NOW - 60, "k1")], quiet=FREE), "drop")

    def test_quiet_rows_do_not_fill_the_daily_cap(self):
        rows = [g.quiet_row(NOW - i, f"k{i}") for i in range(1, g.DAILY_CAP + 3)]
        self.assertEqual(decide(sent=rows), "send")

    def test_quiet_rows_are_not_duplicates(self):
        self.assertEqual(decide(sent=[g.quiet_row(NOW - 60, None)]), "send")


class WhyNow(unittest.TestCase):
    def test_line_from_the_decision_window_reason(self):
        self.assertEqual(g.why_line("peak window open (since wake)"), "Why now: peak window open (since wake)")

    def test_line_drops_digits_and_card_ids(self):
        line = g.why_line("wake event; peak window open (since 1999990000) for t_510c250d in 3 h")
        self.assertTrue(line.startswith("Why now: "))
        self.assertFalse(any(c.isdigit() for c in line), line)
        self.assertNotIn("t_", line)
        self.assertNotIn("()", line)

    def test_empty_or_all_digit_reason_still_gives_a_line(self):
        for r in (None, "", "   ", "12345", "(since 17)"):
            line = g.why_line(r)
            self.assertTrue(line.startswith("Why now: ") and len(line) > len("Why now: "), (r, line))
            self.assertFalse(any(c.isdigit() for c in line), line)

    def test_reason_for_a_class_comes_from_the_decision_window(self):
        self.assertEqual(g.why_reason("critical"), "critical: delivers whatever the window")
        self.assertEqual(g.why_reason("decision"), "anytime job and awake")

    def test_the_always_messages_name_their_event(self):
        self.assertEqual(g.why_reason("report", "Wake-up brief"), "you woke up")
        self.assertEqual(g.why_reason("report", "Back from nap"), "you are back from a nap")
        self.assertEqual(g.why_reason("report", "MIQ for tonight?"), "your wind-down started")

    def test_outgoing_adds_exactly_one_line(self):
        out = g.outgoing("Pick one\nor the other", "Why now: you woke up")
        self.assertEqual(out, "Pick one\nor the other\nWhy now: you woke up")

    def test_outgoing_never_adds_a_second_line(self):
        once = g.outgoing("Pick", "Why now: you woke up")
        self.assertEqual(g.outgoing(once, "Why now: anytime job and awake"), once)

    def test_outgoing_on_an_empty_body_is_the_line(self):
        self.assertEqual(g.outgoing("", "Why now: you woke up"), "Why now: you woke up")

    def test_outgoing_refuses_a_line_that_is_not_one(self):
        with self.assertRaises(ValueError):
            g.outgoing("Pick", "")
        with self.assertRaises(ValueError):
            g.outgoing("Pick", "because 3")


if __name__ == "__main__":
    unittest.main()
