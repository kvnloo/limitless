"""asks: every needs-the-person ask carries a window class; at most one decision per peak window."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import asks  # noqa: E402


class Classify(unittest.TestCase):
    def test_decisions_and_deep_approvals_are_peak(self):
        self.assertEqual(asks.classify({"kind": "decision"}), "peak")
        self.assertEqual(asks.classify({"kind": "decision", "effort": "light"}), "peak")
        self.assertEqual(asks.classify({"kind": "approval", "effort": "deep"}), "peak")

    def test_light_approvals_are_anytime(self):
        self.assertEqual(asks.classify({"kind": "approval", "effort": "light"}), "anytime")
        self.assertEqual(asks.classify({"kind": "approval"}), "anytime")

    def test_fyi_is_trough(self):
        self.assertEqual(asks.classify({"kind": "fyi"}), "trough")
        self.assertEqual(asks.classify({"kind": "fyi", "effort": "deep"}), "trough")

    def test_unknown_kind_is_anytime_never_dropped(self):
        for ask in ({"kind": "poll"}, {}, {"kind": None}, {"kind": 3}, "not a dict", None):
            self.assertEqual(asks.classify(ask), "anytime", ask)

    def test_case_and_space_in_the_fields_do_not_matter(self):
        self.assertEqual(asks.classify({"kind": " Decision "}), "peak")
        self.assertEqual(asks.classify({"kind": "APPROVAL", "effort": "Deep"}), "peak")

    def test_never_reads_the_clock(self):
        same = {"kind": "approval", "effort": "deep", "at": "2026-01-05T03:00:00Z"}
        other = dict(same, at="2026-01-05T21:00:00Z")
        self.assertEqual(asks.classify(same), asks.classify(other))


if __name__ == "__main__":
    unittest.main()
