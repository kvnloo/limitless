"""uptime_audit: per input, fresh / stale / unknown local days from the sync's own runs.jsonl (north-star row one).

A row's ``inputs`` is "stale a,b,c" or absent; a row without it is unknown for that run, never fresh. A day is
fresh for an input when one run that day has ``inputs`` and does not list it; a day with no run or only unknown
rows is unknown. Synthetic rows only, a fixed day, a UTC zone and one fixed non-UTC offset (no DST).
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import uptime_audit as ua  # noqa: E402

UTC = timezone.utc
WEST = timezone(timedelta(hours=-6))      # a fixed offset: no DST
TODAY = date(2030, 1, 15)
_NO = object()


def run(days_ago, hour=9, inputs=_NO, **extra):
    """One sync row ``days_ago`` before TODAY at ``hour`` UTC; ``inputs`` left out unless given."""
    at = datetime(TODAY.year, TODAY.month, TODAY.day, hour, tzinfo=UTC) - timedelta(days=days_ago)
    r = {"at": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "job": "sync", "ok": True}
    if inputs is not _NO:
        r["inputs"] = inputs
    r.update(extra)
    return r


def counts(a, name):
    c = a["inputs"][name]
    return c["fresh"], c["stale"], c["unknown"]


class Rows(unittest.TestCase):
    def test_stale_names_reads_the_string_and_absent_is_unknown(self):
        self.assertEqual(ua.stale_names(run(0, inputs="stale whoop,oura")), {"whoop", "oura"})
        self.assertEqual(ua.stale_names(run(0, inputs="stale  phoneApps , desktopAW ")), {"phoneApps", "desktopAW"})
        self.assertEqual(ua.stale_names(run(0, inputs="stale")), set())
        self.assertIsNone(ua.stale_names(run(0)))
        for odd in ("", "fresh", "whoop", "stalewhoop", None, 3, ["whoop"], {"stale": "whoop"}):
            self.assertIsNone(ua.stale_names(run(0, inputs=odd)), odd)

    def test_parse_lines_keeps_dated_objects_and_counts_the_rest(self):
        text = "\n".join([json.dumps(run(0, inputs="stale whoop")), "torn {", json.dumps([1]),
                          json.dumps({"job": "sync"}), json.dumps({"at": "not a time"}), "", json.dumps(run(1))])
        rows, skipped = ua.parse_lines(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(skipped, 4)

    def test_read_log_is_none_when_missing(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(ua.read_log(Path(d) / "runs.jsonl"))
            p = Path(d) / "runs.jsonl"
            p.write_text(json.dumps(run(0)) + "\n")
            self.assertEqual(ua.read_log(p), ([run(0)], 0))


class Config(unittest.TestCase):
    def test_window_days_and_target_defaults_and_bad_values(self):
        self.assertEqual((ua.window_days({}), ua.target({})), (28, 0.95))
        self.assertEqual((ua.window_days({"uptime_days": 14}), ua.target({"uptime_target": 0.9})), (14, 0.9))
        for bad in (0, -3, True, "28", 2.5, None):
            self.assertEqual(ua.window_days({"uptime_days": bad}), 28, bad)
        for bad in (0, -0.1, 1.5, True, "0.9", float("nan"), None):
            self.assertEqual(ua.target({"uptime_target": bad}), 0.95, bad)
        self.assertEqual(ua.target({"uptime_target": 1}), 1.0)
        self.assertEqual((ua.window_days(None), ua.target(None)), (28, 0.95))


class Audit(unittest.TestCase):
    def test_window_is_the_n_local_days_ending_today(self):
        a = ua.audit([], days=28, today=TODAY, tz=UTC)
        self.assertEqual(len(a["days"]), 28)
        self.assertEqual(a["days"][-1]["day"], "2030-01-15")
        self.assertEqual(a["days"][0]["day"], "2029-12-19")
        self.assertEqual(a["window_days"], 28)

    def test_old_rows_without_inputs_are_unknown_never_fresh(self):
        rows = [run(n) for n in range(28)]
        a = ua.audit(rows, inputs=["whoop", "phoneApps"], today=TODAY, tz=UTC)
        self.assertEqual(counts(a, "whoop"), (0, 0, 28))
        self.assertEqual(counts(a, "phoneApps"), (0, 0, 28))
        self.assertEqual((a["known_days"], a["all_fresh_days"]), (0, 0))
        self.assertTrue(all(d["all_fresh"] is None and d["stale"] is None for d in a["days"]))

    def test_one_run_not_listing_an_input_makes_the_day_fresh_for_it(self):
        rows = [run(0, 1, inputs="stale whoop,oura"), run(0, 5, inputs="stale whoop"), run(0, 7)]
        a = ua.audit(rows, days=1, today=TODAY, tz=UTC)
        self.assertEqual(counts(a, "whoop"), (0, 1, 0))
        self.assertEqual(counts(a, "oura"), (1, 0, 0))
        self.assertEqual(a["days"][0]["stale"], ["whoop"])
        self.assertIs(a["days"][0]["all_fresh"], False)
        self.assertEqual((a["days"][0]["runs"], a["days"][0]["known_runs"]), (3, 2))

    def test_mixed_old_rows_stale_rows_and_whole_day_gaps(self):
        rows = [run(n) for n in range(20, 28)]                              # eight old days: unknown
        rows += [run(n, inputs="stale whoop,oura") for n in range(10, 20)]  # ten days: both wearables stale
        rows += [run(n, inputs="stale") for n in (0, 1, 2, 3, 4, 5)]        # six days all fresh; days 6-9: no run
        rows += [run(3, 2, inputs="stale whoop")]                           # stale earlier, fresh later that day
        a = ua.audit(rows, inputs=["phoneApps", "whoop", "oura"], today=TODAY, tz=UTC)
        self.assertEqual(counts(a, "phoneApps"), (16, 0, 12))
        self.assertEqual(counts(a, "whoop"), (6, 10, 12))
        self.assertEqual(counts(a, "oura"), (6, 10, 12))
        self.assertEqual((a["known_days"], a["all_fresh_days"]), (16, 6))
        for name in a["inputs"]:
            self.assertEqual(sum(counts(a, name)), 28)

    def test_inputs_seen_only_as_stale_join_the_set(self):
        a = ua.audit([run(0, inputs="stale ownerMessages"), run(1, inputs="stale")], days=2, today=TODAY, tz=UTC)
        self.assertEqual(sorted(a["inputs"]), ["ownerMessages"])
        self.assertEqual(counts(a, "ownerMessages"), (1, 1, 0))

    def test_outage_ignore_leaves_an_input_out(self):
        rows = [run(n, inputs="stale desktopAW") for n in range(3)]
        a = ua.audit(rows, inputs=["phoneApps", "desktopAW"], days=3, today=TODAY, tz=UTC, ignore={"desktopAW"})
        self.assertEqual(sorted(a["inputs"]), ["phoneApps"])
        self.assertEqual(a["all_fresh_days"], 3)
        self.assertEqual(a["days"][0]["stale"], [])

    def test_a_non_utc_zone_moves_early_utc_runs_to_the_day_before(self):
        rows = [run(0, 3, inputs="stale whoop"), run(0, 9, inputs="stale")]   # 03:00Z is the evening before at -6
        utc = ua.audit(rows, days=2, today=TODAY, tz=UTC)
        self.assertEqual(counts(utc, "whoop"), (1, 0, 1))
        west = ua.audit(rows, days=2, today=TODAY, tz=WEST)
        self.assertEqual(counts(west, "whoop"), (1, 1, 0))
        self.assertEqual([d["day"] for d in west["days"]], ["2030-01-14", "2030-01-15"])

    def test_rows_outside_the_window_and_after_today_are_left_out(self):
        rows = [run(40, inputs="stale whoop"), run(-2, inputs="stale whoop"), run(0, inputs="stale")]
        a = ua.audit(rows, inputs=["whoop"], days=7, today=TODAY, tz=UTC)
        self.assertEqual(counts(a, "whoop"), (1, 0, 6))

    def test_today_defaults_to_the_newest_rows_day(self):
        a = ua.audit([run(3, inputs="stale"), run(5)], days=2, tz=UTC)
        self.assertEqual(a["days"][-1]["day"], "2030-01-12")
        self.assertEqual(ua.audit([], tz=UTC)["days"], [])

    def test_bad_rows_are_counted_not_read(self):
        a = ua.audit([run(0, inputs="stale"), {"at": "nope"}, "x"], days=1, today=TODAY, tz=UTC, skipped=2)
        self.assertEqual(a["skipped"], 4)
        self.assertEqual(a["known_days"], 1)

    def test_target_and_share_are_over_the_whole_window(self):
        a = ua.audit([run(n, inputs="stale") for n in range(10)], days=20, today=TODAY, tz=UTC, target=0.9)
        self.assertEqual(a["target"], 0.9)
        self.assertEqual(a["all_fresh_share"], 0.5)


if __name__ == "__main__":
    unittest.main()
