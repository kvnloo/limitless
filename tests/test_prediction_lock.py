"""prediction.lock: one prediction per habit week, locked before the week has check-ins, never rewritten.
Synthetic fixtures only; nothing sends."""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import prediction  # noqa: E402

NOW = 1894708800.0          # fixture clock, 2030-01-15T12:00:00Z
WEEK = "2030-01-15"
DAY1 = date(2030, 1, 15)


class PredictionLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)
        self.pj = self.st / prediction.PREDICTIONS_FILE

    def tearDown(self):
        self.tmp.cleanup()

    def habit(self, week_of=WEEK, checkins=None):
        (self.st / "habit.json").write_text(json.dumps(
            {"habit": "Synthetic habit", "week_of": week_of, "checkins": checkins or {}}))

    def rows(self):
        return [json.loads(x) for x in self.pj.read_text().splitlines()] if self.pj.exists() else []

    def lock(self, text="More done days than last week", metric="logged", direction="at_least 4 of 7",
             write=True, today=DAY1, week_of=WEEK):
        return prediction.lock(self.st, week_of, text, metric, direction, write=write, today=today, now=NOW)

    def assert_refused(self, r, words):
        self.assertEqual(r["action"], prediction.REFUSED, r)
        self.assertIn(words, r["reason"])
        self.assertEqual(re.findall(r"\d", r["reason"]), [], r["reason"])

    def test_dry_run_writes_nothing(self):
        self.habit()
        r = self.lock(write=False)
        self.assertEqual(r["action"], prediction.WOULD_LOCK)
        self.assertFalse(self.pj.exists())

    def test_write_appends_one_row_with_locked_at(self):
        self.habit()
        r = self.lock()
        self.assertEqual(r["action"], prediction.LOCKED)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["kind"], row["week_of"], row["metric"], row["direction"]),
                         ("prediction", WEEK, "logged", "at_least 4 of 7"))
        self.assertEqual(row["text"], "More done days than last week")
        self.assertEqual(row["locked_at"], "2030-01-15T12:00:00+00:00")
        self.assertEqual(oct(self.pj.stat().st_mode & 0o777), "0o600")

    def test_before_the_week_starts_it_locks(self):
        r = self.lock(week_of="2030-01-16")           # no habit.json yet, the week starts tomorrow
        self.assertEqual(r["action"], prediction.LOCKED, r)

    def test_day_one_with_a_checkin_still_locks(self):
        self.habit(checkins={WEEK: "Done"})           # started zero days ago
        self.assertEqual(self.lock()["action"], prediction.LOCKED)

    def test_a_started_week_with_checkins_is_refused(self):
        self.habit(week_of="2030-01-13", checkins={"2030-01-13": "Done"})
        r = self.lock(week_of="2030-01-13")
        self.assert_refused(r, "check-ins")
        self.assertFalse(self.pj.exists())

    def test_a_skip_counts_as_a_logged_checkin(self):
        self.habit(week_of="2030-01-13", checkins={"2030-01-14": "Skipped"})
        self.assert_refused(self.lock(week_of="2030-01-13"), "check-ins")

    def test_a_started_week_with_no_checkins_still_locks(self):
        self.habit(week_of="2030-01-13", checkins={"2030-01-13": "maybe"})   # unlogged
        self.assertEqual(self.lock(week_of="2030-01-13")["action"], prediction.LOCKED)

    def test_a_week_already_over_is_refused(self):
        self.assert_refused(self.lock(week_of="2030-01-01"), "over")
        self.assertFalse(self.pj.exists())

    def test_a_second_lock_is_refused_and_the_first_is_never_rewritten(self):
        self.habit()
        self.lock()
        before = self.pj.read_bytes()
        for write in (True, False):
            r = self.lock(text="Something else", direction="up", metric="sleep_h", write=write)
            self.assert_refused(r, "already locked")
        self.assertEqual(self.pj.read_bytes(), before)

    def test_another_week_locks_its_own(self):
        self.lock(week_of="2030-01-16")
        self.assertEqual(self.lock(week_of="2030-01-17")["action"], prediction.LOCKED)
        self.assertEqual(len(self.rows()), 2)

    def test_empty_text_is_refused(self):
        self.habit()
        for text in ("", "   ", None, 5):
            self.assert_refused(self.lock(text=text), "empty")
        self.assertFalse(self.pj.exists())

    def test_metric_and_direction_are_checked(self):
        self.habit()
        for metric, direction, words in (
                ("weight_kg", "down", "metric"),
                ("logged", "sideways", "direction"),
                ("logged", "at_least 8 of 7", "direction"),
                ("logged", "at_least 0 of 7", "direction"),
                ("logged", "up", "at_least"),
                ("sleep_h", "at_least 4 of 7", "up or down")):
            self.assert_refused(self.lock(metric=metric, direction=direction), words)
        self.assertFalse(self.pj.exists())

    def test_state_metrics_take_up_or_down(self):
        self.lock(week_of="2030-01-16", metric="sleep_h", direction="up")
        self.lock(week_of="2030-01-17", metric="readiness", direction="down")
        self.assertEqual([r["metric"] for r in self.rows()], ["sleep_h", "readiness"])

    def test_bad_week_of_is_refused(self):
        self.assert_refused(self.lock(week_of="soon"), "date")

    def test_locked_reads_the_week(self):
        self.habit()
        self.assertIsNone(prediction.locked(self.st, WEEK))
        self.lock()
        self.assertEqual(prediction.locked(self.st, WEEK)["text"], "More done days than last week")
        self.assertIsNone(prediction.locked(self.st, "2030-01-16"))

    def test_a_torn_line_is_skipped_and_the_next_row_starts_clean(self):
        self.pj.write_text('{"kind": "prediction", "week_of": "2030-01-1')
        self.habit()
        self.assertEqual(self.lock()["action"], prediction.LOCKED)
        self.assertEqual(prediction.locked(self.st, WEEK)["week_of"], WEEK)

    def test_labels_have_no_digits(self):
        self.habit()
        for r in (self.lock(write=False), self.lock(), self.lock()):
            self.assertEqual(re.findall(r"\d", prediction.label(r)), [], prediction.label(r))


if __name__ == "__main__":
    unittest.main()
