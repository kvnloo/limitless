"""prediction.receipt with a lag: pending (nothing written) until the lagged span is over, then judged on that
span against the week before the habit week; fewer than three days in the judged span is inconclusive, never a
guess. Synthetic fixtures only; nothing sends."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import prediction, tools  # noqa: E402

NOW = 1894708800.0
WEEK = date(2030, 1, 15)
DONE5 = {(WEEK + timedelta(days=i)).isoformat(): "Done" for i in range(5)}


class LaggedReceipt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name)
        self.habit(DONE5)

    def habit(self, checkins):
        (self.st / "habit.json").write_text(json.dumps(
            {"habit": "Synthetic habit", "week_of": WEEK.isoformat(), "checkins": checkins}))

    def predict(self, lag, direction="up"):
        r = prediction.lock(self.st, WEEK.isoformat(), "Synthetic prediction", "sleep_h", direction, write=True,
                            today=WEEK, now=NOW, falsifier="no change a week later", lag_days=lag)
        self.assertEqual(r["action"], prediction.LOCKED, r)

    def digests(self, by_offset):
        """{day offset from WEEK: synthetic value}."""
        lines = []
        for off, v in sorted(by_offset.items()):
            d = WEEK + timedelta(days=off)
            lines.append({"date": d.isoformat(), "at": d.isoformat() + "T07:00:00Z",
                          "metrics": {"sleep_h": {"value": v, "modality": "proxy"}}})
        (self.st / "digests.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))

    def span(self, first, value, n=7):
        return {first + i: value for i in range(n)}

    def receipt(self, day, write=True):
        return prediction.receipt(self.st, WEEK.isoformat(), write=write, today=WEEK + timedelta(days=day),
                                  now=NOW + day * 86400)

    def receipts(self):
        return [r for r in prediction.rows(self.st) if r.get("kind") == "receipt"]

    def test_pending_until_the_lagged_span_is_over_and_nothing_is_written(self):
        self.predict(7)
        for day in (3, 7, 10, 13):
            r = self.receipt(day)
            self.assertEqual((r["action"], r["verdict"], r["receipt"]), (prediction.PENDING, "pending", None), day)
            self.assertEqual(re.findall(r"\d", r["reason"]), [], r["reason"])
            self.assertIn("later", r["reason"])
        self.assertEqual(self.receipts(), [])

    def test_judged_on_the_lagged_span_not_the_habit_week(self):
        # before: lower; habit week: lower still (lag zero would contradict); a week after: higher
        self.digests({**self.span(-7, 6.0), **self.span(0, 5.0), **self.span(7, 7.0)})
        self.predict(7)
        r = self.receipt(14)
        self.assertEqual(r["action"], prediction.WROTE, r)
        rc = r["receipt"]
        self.assertEqual((rc["verdict"], rc["outcome"]), ("supports", "higher"))
        self.assertIn("the week after the habit week", rc["reason"])
        self.assertEqual(re.findall(r"\d", json.dumps({k: v for k, v in rc.items()
                                                       if k not in ("week_of", "locked_at", "at")})), [])
        self.assertEqual(len(self.receipts()), 1)
        self.assertEqual(self.receipt(15)["action"], prediction.REFUSED)   # one per prediction

    def test_two_weeks_waits_for_the_second_week_after(self):
        self.digests({**self.span(-7, 6.0), **self.span(7, 7.0), **self.span(14, 5.0)})
        self.predict(14)
        self.assertEqual(self.receipt(20)["action"], prediction.PENDING)
        rc = self.receipt(21)["receipt"]
        self.assertEqual((rc["verdict"], rc["outcome"]), ("contradicts", "lower"))

    def test_fewer_than_three_days_in_the_judged_span_is_inconclusive(self):
        self.digests({**self.span(-7, 6.0), **self.span(0, 7.0), **self.span(7, 7.0, n=2)})
        self.predict(7)
        rc = self.receipt(14)["receipt"]
        self.assertEqual(rc["verdict"], "inconclusive")
        self.assertEqual(re.findall(r"\d", rc["reason"]), [], rc["reason"])

    def test_fewer_than_three_logged_habit_days_is_inconclusive(self):
        self.habit({WEEK.isoformat(): "Done", (WEEK + timedelta(days=1)).isoformat(): "Skipped"})
        self.digests({**self.span(-7, 6.0), **self.span(7, 7.0)})
        self.predict(7)
        self.assertEqual(self.receipt(14)["receipt"]["verdict"], "inconclusive")

    def test_no_lag_is_as_before(self):
        self.digests({**self.span(-7, 6.0), **self.span(0, 7.0)})
        self.predict(0)
        self.assertEqual(self.receipt(6)["action"], prediction.REFUSED)
        rc = self.receipt(7)["receipt"]
        self.assertEqual(rc["verdict"], "supports")
        self.assertIn("the habit week", rc["reason"])

    def test_an_old_row_without_a_lag_is_judged_on_its_week(self):
        old = {"kind": "prediction", "week_of": WEEK.isoformat(), "text": "Synthetic prediction",
               "metric": "sleep_h", "direction": "up", "locked_at": "2030-01-15T00:00:00+00:00"}
        (self.st / prediction.PREDICTIONS_FILE).write_text(json.dumps(old) + "\n")
        self.digests({**self.span(-7, 6.0), **self.span(0, 7.0)})
        self.assertEqual(self.receipt(7)["receipt"]["verdict"], "supports")

    def test_an_unreadable_lag_is_inconclusive(self):
        bad = {"kind": "prediction", "week_of": WEEK.isoformat(), "text": "Synthetic prediction",
               "metric": "sleep_h", "direction": "up", "lag_days": 3, "locked_at": "2030-01-15T00:00:00+00:00"}
        (self.st / prediction.PREDICTIONS_FILE).write_text(json.dumps(bad) + "\n")
        self.assertEqual(self.receipt(30)["receipt"]["verdict"], "inconclusive")

    def test_the_habit_receipt_tool_says_pending_in_words(self):
        self.predict(7)
        out = tools.habit_receipt(self.st, WEEK + timedelta(days=9), NOW, confirm=True)
        self.assertEqual(out["value"]["action"], prediction.PENDING)
        self.assertEqual(out["label"]["label"], "outcome pending: judged later")
        self.assertEqual(self.receipts(), [])

    def test_the_habit_receipt_tool_picks_a_due_lagged_prediction(self):
        self.digests({**self.span(-7, 6.0), **self.span(7, 7.0)})
        self.predict(7)
        out = tools.habit_receipt(self.st, WEEK + timedelta(days=14), NOW, confirm=True)
        self.assertEqual(out["value"]["action"], prediction.WROTE, out)


if __name__ == "__main__":
    unittest.main()
