"""send_gate.decide(window=...) tests. Synthetic fixtures only.

tests/test_send_gate.py is left unchanged: with no window every result is the same as before.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import decision_window as dw  # noqa: E402
from limitless import send_gate as g  # noqa: E402

NOW = 2_000_000_000.0


def win(job="peak", cls="peak", budget_left=1):
    return dw.JobWindow(job, dw.StaticProvider(cls, since="wake").current(), budget_left)


def decide(tag="x", title="T", body="b", cls="decision", sent=(), asleep=False, window=None):
    return g.decide(tag, title, body, cls, NOW, list(sent), asleep, window=window)


class SendGateWindow(unittest.TestCase):
    def test_no_window_keeps_old_result(self):
        self.assertEqual(decide(window=None), "send")

    def test_open_matching_window_sends(self):
        self.assertEqual(decide(window=win()), "send")

    def test_window_mismatch_holds(self):
        self.assertEqual(decide(window=win(job="peak", cls="trough")), "hold")

    def test_unknown_window_holds(self):
        self.assertEqual(decide(window=win(cls="unknown")), "hold")

    def test_spent_peak_budget_drops(self):
        self.assertEqual(decide(window=win(budget_left=0)), "drop")

    def test_critical_ignores_window(self):
        self.assertEqual(decide(cls="critical", window=win(job="peak", cls="unknown", budget_left=0)), "send")

    def test_fold_and_log_come_before_the_window(self):
        self.assertEqual(decide(tag="asks", window=win(cls="trough")), "fold")
        self.assertEqual(decide(cls="report", window=win(cls="trough")), "log")

    def test_sleep_hold_comes_before_the_window(self):
        self.assertEqual(decide(asleep=True, window=win()), "hold")

    def test_back_from_nap_still_skips_sleep_hold_with_anytime_window(self):
        w = win(job="anytime", cls="unknown")
        self.assertEqual(decide(tag="limitless", title="Back from nap", asleep=True, window=w), "send")

    def test_window_deliver_still_respects_dedupe_and_cap(self):
        k = g.key("T", "b")
        self.assertEqual(decide(sent=[{"t": NOW - 60, "k": k}], window=win()), "duplicate")
        sent = [{"t": NOW - i, "k": str(i)} for i in range(g.DAILY_CAP)]
        self.assertEqual(decide(sent=sent, window=win()), "cap")


if __name__ == "__main__":
    unittest.main()
