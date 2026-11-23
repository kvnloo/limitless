"""prediction.receipt: after day seven, one append-only receipt judges the locked prediction against the
week: supports, contradicts or inconclusive (fewer than three logged days is never contradicts).
Synthetic fixtures only; nothing sends."""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import prediction  # noqa: E402

NOW = 1894708800.0
WEEK = date(2030, 1, 15)
DAY8 = WEEK + timedelta(days=7)


def days(*answers):
    return {(WEEK + timedelta(days=i)).isoformat(): a for i, a in enumerate(answers) if a}


class PredictionReceipt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)
        self.pj = self.st / prediction.PREDICTIONS_FILE

    def tearDown(self):
        self.tmp.cleanup()

    def habit(self, checkins, name="habit.json"):
        (self.st / name).write_text(json.dumps(
            {"habit": "Synthetic habit", "week_of": WEEK.isoformat(), "checkins": checkins}))

    def predict(self, metric="logged", direction="at_least 4 of 7"):
        r = prediction.lock(self.st, WEEK.isoformat(), "Synthetic prediction", metric, direction, write=True,
                            today=WEEK, now=NOW)
        self.assertEqual(r["action"], prediction.LOCKED, r)

    def digests(self, before, during):
        lines = []
        for i, v in enumerate(before):
            d = WEEK - timedelta(days=len(before) - i)
            lines.append({"date": d.isoformat(), "at": d.isoformat() + "T07:00:00Z",
                          "metrics": {"sleep_h": {"value": v, "modality": "proxy"}}})
        for i, v in enumerate(during):
            d = WEEK + timedelta(days=i)
            lines.append({"date": d.isoformat(), "at": d.isoformat() + "T07:00:00Z",
                          "metrics": {"sleep_h": {"value": v, "modality": "proxy"}}})
        (self.st / "digests.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))

    def receipt(self, write=True, today=DAY8):
        return prediction.receipt(self.st, WEEK.isoformat(), write=write, today=today, now=NOW + 7 * 86400)

    def verdict(self, **kw):
        r = self.receipt(**kw)
        self.assertEqual(r["action"], prediction.WROTE, r)
        self.assertEqual(re.findall(r"\d", r["receipt"]["reason"]), [], r["receipt"]["reason"])
        return r["receipt"]

    def receipts(self):
        return [r for r in prediction.rows(self.st) if r.get("kind") == "receipt"]

    def test_supports_when_the_logged_share_reaches_k_of_m(self):
        self.habit(days("Done", "Done", "Done", "Done", "No", "Done", "Skipped"))
        self.predict()
        rc = self.verdict()
        self.assertEqual((rc["verdict"], rc["outcome"]), ("supports", "5 of 6 logged days"))
        self.assertEqual(rc["locked_at"], prediction.locked(self.st, WEEK.isoformat())["locked_at"])

    def test_contradicts_when_it_falls_short_with_every_day_logged(self):
        self.habit(days("Done", "No", "No", "Done", "No", "No", "Done"))
        self.predict()
        self.assertEqual(self.verdict()["verdict"], "contradicts")

    def test_fewer_than_three_logged_days_is_inconclusive_never_contradicts(self):
        self.habit(days("No", "No", "Skipped", "Skipped"))
        self.predict()
        rc = self.verdict()
        self.assertEqual(rc["verdict"], "inconclusive")
        self.assertIn("fewer than three logged days", rc["reason"])

    def test_unlogged_days_that_could_change_it_are_inconclusive(self):
        self.habit(days("Done", "No", "No", "Done"))          # three days unlogged, could have been Done
        self.predict()
        self.assertEqual(self.verdict()["verdict"], "inconclusive")

    def test_a_kept_week_is_read_after_a_new_week_started(self):
        self.habit(days("Done", "Done", "Done", "Done", "Done", "Done", "Done"), name=f"habit-{WEEK}.json")
        (self.st / "habit.json").write_text(json.dumps({"habit": "Next", "week_of": DAY8.isoformat(), "checkins": {}}))
        self.predict()
        self.assertEqual(self.verdict()["verdict"], "supports")

    def test_state_metric_up_supports_when_the_week_is_higher(self):
        self.habit(days("Done", "Done", "No", "Done"))
        self.digests([6.0, 6.2, 6.1, 6.0], [7.0, 7.1, 6.9, 7.2])
        self.predict("sleep_h", "up")
        rc = self.verdict()
        self.assertEqual((rc["verdict"], rc["outcome"]), ("supports", "higher"))

    def test_state_metric_down_contradicts_when_the_week_is_higher(self):
        self.habit(days("Done", "Done", "No", "Done"))
        self.digests([6.0, 6.2, 6.1, 6.0], [7.0, 7.1, 6.9, 7.2])
        self.predict("sleep_h", "down")
        self.assertEqual(self.verdict()["verdict"], "contradicts")

    def test_state_metric_with_too_few_values_is_inconclusive(self):
        self.habit(days("Done", "Done", "No", "Done"))
        self.digests([6.0, 6.2], [7.0, 7.1, 6.9, 7.2])
        self.predict("sleep_h", "up")
        self.assertEqual(self.verdict()["verdict"], "inconclusive")

    def test_state_metric_with_too_few_logged_days_is_inconclusive(self):
        self.habit(days("Done", "No"))
        self.digests([6.0, 6.2, 6.1, 6.0], [5.0, 5.1, 4.9, 5.2])
        self.predict("sleep_h", "up")
        self.assertEqual(self.verdict()["verdict"], "inconclusive")

    def test_reasons_never_echo_raw_values(self):
        self.habit(days("Done", "Done", "No", "Done"))
        self.digests([6.0, 6.2, 6.1, 6.0], [7.0, 7.1, 6.9, 7.2])
        self.predict("sleep_h", "up")
        self.receipt()
        self.assertEqual(re.findall(r"\d", json.dumps({k: v for k, v in self.receipts()[0].items()
                                                         if k not in ("week_of", "locked_at", "at")})), [])

    def test_before_day_eight_it_is_refused(self):
        self.habit(days("Done", "Done", "Done"))
        self.predict()
        r = self.receipt(today=WEEK + timedelta(days=6))
        self.assertEqual(r["action"], prediction.REFUSED)
        self.assertIn("not over", r["reason"])
        self.assertEqual(self.receipts(), [])

    def test_no_prediction_is_refused(self):
        r = self.receipt()
        self.assertEqual(r["action"], prediction.REFUSED)
        self.assertIn("no prediction", r["reason"])
        self.assertFalse(self.pj.exists())

    def test_dry_run_says_the_verdict_and_writes_nothing(self):
        self.habit(days("Done", "Done", "Done", "Done"))
        self.predict()
        before = self.pj.read_bytes()
        r = self.receipt(write=False)
        self.assertEqual((r["action"], r["receipt"]["verdict"]), (prediction.WOULD_WRITE, "supports"))
        self.assertEqual(self.pj.read_bytes(), before)

    def test_one_receipt_per_prediction_append_only(self):
        self.habit(days("Done", "Done", "Done", "Done"))
        self.predict()
        self.receipt()
        before = self.pj.read_bytes()
        self.habit(days("No", "No", "No", "No", "No", "No", "No"))      # the week changes later
        r = self.receipt()
        self.assertEqual(r["action"], prediction.REFUSED)
        self.assertIn("already written", r["reason"])
        self.assertEqual(self.pj.read_bytes(), before)
        self.assertEqual(len(self.receipts()), 1)
        self.assertEqual(prediction.receipt_for(self.st, WEEK.isoformat())["verdict"], "supports")

    def test_receipt_labels_have_no_digits(self):
        self.habit(days("Done", "Done", "Done", "Done"))
        self.predict()
        for r in (self.receipt(write=False), self.receipt(), self.receipt()):
            self.assertEqual(re.findall(r"\d", prediction.receipt_label(r)), [], prediction.receipt_label(r))


if __name__ == "__main__":
    unittest.main()
