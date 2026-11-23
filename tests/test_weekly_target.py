"""The weekly target: "most days" of the one habit week, never a streak. Synthetic check-ins only.

Done counts toward the target. No, Skip and a day with no answer are not failures: they never reduce
anything, and nothing resets. No started week is unknown (None), never zero.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import weekly_target as wt  # noqa: E402

START = date(2031, 3, 3)


def day(i):
    return (START + timedelta(days=i)).isoformat()


def checkins(*words):
    """Check-ins for days one, two, ... of the week; None leaves that day with no answer."""
    return {day(i): w for i, w in enumerate(words) if w is not None}


class Progress(unittest.TestCase):
    def test_shape(self):
        p = wt.progress(checkins("Done"), START, START)
        self.assertEqual(set(p), {"done", "logged", "target", "reached", "label"})
        self.assertEqual(p["label"]["tier"], "T1")

    def test_default_target_is_four_of_seven(self):
        self.assertEqual(wt.DEFAULT_TARGET_DAYS, 4)
        self.assertEqual(wt.progress({}, START, START)["target"], 4)

    def test_no_week_is_unknown_not_zero(self):
        for start in (None, "", "not a date"):
            self.assertIsNone(wt.progress(checkins("Done"), start, START))
        self.assertIsNone(wt.progress(checkins("Done"), START, START - timedelta(days=1)))

    def test_iso_week_start_is_read(self):
        self.assertEqual(wt.progress(checkins("Done"), START.isoformat(), START)["done"], 1)

    def test_done_counts_no_and_skip_do_not_reduce(self):
        base = wt.progress(checkins("Done", None, "Done"), START, START + timedelta(days=4))
        more = wt.progress(checkins("Done", "No", "Done", "Skipped", "skip"), START, START + timedelta(days=4))
        self.assertEqual((base["done"], more["done"]), (2, 2))
        self.assertEqual(base["reached"], more["reached"])
        self.assertEqual(base["label"]["label"], more["label"]["label"])

    def test_logged_is_done_plus_no(self):
        p = wt.progress(checkins("Done", "No", "Skipped", None, "Done"), START, START + timedelta(days=6))
        self.assertEqual((p["done"], p["logged"]), (2, 3))

    def test_no_streak_nothing_resets(self):
        # Done, a gap of No / unanswered days, then Done again: every Done still counts.
        p = wt.progress(checkins("Done", "Done", "No", None, "Done", "Done"), START, START + timedelta(days=5))
        self.assertEqual(p["done"], 4)
        self.assertTrue(p["reached"])
        self.assertNotIn("streak", json.dumps(p).lower())

    def test_labels(self):
        self.assertEqual(wt.progress({}, START, START)["label"]["label"], wt.NOT_STARTED)
        self.assertEqual(wt.progress(checkins("No", "Skipped"), START, START + timedelta(days=1))["label"]["label"],
                         wt.NOT_STARTED)
        self.assertEqual(wt.progress(checkins("Done"), START, START)["label"]["label"], wt.ON_THE_WAY)
        p = wt.progress(checkins("Done", "Done", "Done", "Done"), START, START + timedelta(days=3))
        self.assertEqual((p["reached"], p["label"]["label"]), (True, wt.REACHED))
        self.assertEqual(wt.REACHED, "target reached this week")

    def test_week_closed_after_day_seven(self):
        c = checkins("Done", "Done", "Done", "Done")
        self.assertEqual(wt.progress(c, START, START + timedelta(days=6))["label"]["label"], wt.REACHED)
        p = wt.progress(c, START, START + timedelta(days=7))
        self.assertEqual((p["label"]["label"], p["reached"], p["done"]), (wt.CLOSED, True, 4))

    def test_only_the_week_and_days_up_to_today_count(self):
        c = dict(checkins("Done"), **{day(-1): "Done", day(7): "Done", day(3): "Done"})
        self.assertEqual(wt.progress(c, START, START + timedelta(days=1))["done"], 1)
        self.assertEqual(wt.progress(c, START, START + timedelta(days=9))["done"], 2)

    def test_unknown_words_are_unlogged(self):
        p = wt.progress({day(0): "maybe", day(1): 3, day(2): None, "junk": "Done"}, START, START + timedelta(days=2))
        self.assertEqual((p["done"], p["logged"]), (0, 0))
        self.assertIsNotNone(wt.progress("not a table", START, START))

    def test_target_days_bounds(self):
        self.assertEqual(wt.progress({}, START, START, target_days=7)["target"], 7)
        for bad in (0, 8, -1, "4", 4.5, True, None):
            self.assertEqual(wt.progress({}, START, START, target_days=bad)["target"], 4, bad)

    def test_labels_are_digit_free(self):
        for w in wt.LABELS:
            self.assertFalse(any(ch.isdigit() for ch in w), w)
        for n in range(8):
            for t in range(9):
                p = wt.progress(checkins(*["Done"] * n), START, START + timedelta(days=t))
                self.assertFalse(any(ch.isdigit() for ch in p["label"]["label"]))

    def test_label_modality(self):
        self.assertEqual(wt.progress({}, START, START)["label"]["modality"], "self_report")
        self.assertEqual(wt.progress({}, START, START, modality="proxy")["label"]["modality"], "proxy")


class Config(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_without_config(self):
        self.assertEqual(wt.target_days(self.env), 4)

    def test_config_key(self):
        self.cfg.write_text(json.dumps({"habit_target_days": 5}))
        self.assertEqual(wt.target_days(self.env), 5)
        for bad in (0, 9, "five", 3.5, False):
            self.cfg.write_text(json.dumps({"habit_target_days": bad}))
            self.assertEqual(wt.target_days(self.env), 4, bad)


if __name__ == "__main__":
    unittest.main()
