"""uptime_audit loop gaps: stretches when the sync loop itself did not run, read from the rows' own ``at`` times.

A gap is the time between two runs that is longer than the limit: config ``loop_gap_limit_s``, else three times
the median spacing of the window's rows. A gap still open now (the newest run older than the limit) is said
first. Words only, no digit. Synthetic runs.jsonl rows only, a fixed clock and a UTC zone.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import unittest
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import uptime_audit as ua  # noqa: E402

UTC = timezone.utc
TODAY = date(2030, 1, 15)
END = datetime(2030, 1, 15, 21, tzinfo=UTC).timestamp()   # the newest regular run: 21:00 on TODAY
M, H, D = 60.0, 3600.0, 86400.0


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def rows_at(times, inputs="stale"):
    return [{"at": iso(t), "job": "sync", "ok": True, "inputs": inputs} for t in sorted(times)]


def every(step, span=28 * D - 22 * H, end=END):
    """Run times every ``step`` seconds over ``span`` seconds ending at ``end`` (inside the window)."""
    n = int(span // step)
    return [end - k * step for k in range(n, -1, -1)]


def without(times, start, stop):
    """``times`` with the runs strictly between ``start`` and ``stop`` taken out (a loop-down stretch)."""
    return [t for t in times if not start < t < stop]


def audit(times, now=END + 10 * M, **kw):
    return ua.audit(rows_at(times), days=kw.pop("days", 28), today=TODAY, tz=UTC, now=now, **kw)


def words(a):
    w = a["label"]["label"]
    assert not any(c.isdigit() for c in w), w
    return w


HOURLY = every(H)


class Spacing(unittest.TestCase):
    def test_the_usual_spacing_is_the_median_of_the_rows_own_spacing(self):
        self.assertEqual(ua.usual_spacing(HOURLY), H)
        self.assertEqual(ua.usual_spacing([0.0, 10.0, 20.0, 1000.0]), 10.0)
        self.assertEqual(ua.usual_spacing([30.0, 0.0, 20.0, 10.0]), 10.0)  # unsorted in, sorted first
        self.assertEqual(ua.usual_spacing([0.0, 10.0, 30.0]), 15.0)    # an even count: the middle two
        self.assertIsNone(ua.usual_spacing([5.0]))
        self.assertIsNone(ua.usual_spacing([]))
        self.assertIsNone(ua.usual_spacing([5.0, 5.0, 5.0]))           # no positive spacing at all

    def test_gap_limit_config_and_bad_values(self):
        self.assertIsNone(ua.gap_limit({}))
        self.assertIsNone(ua.gap_limit(None))
        self.assertEqual(ua.gap_limit({"loop_gap_limit_s": 7200}), 7200.0)
        self.assertEqual(ua.gap_limit({"loop_gap_limit_s": 900.5}), 900.5)
        for bad in (0, -5, True, "7200", float("nan"), float("inf"), None, [1]):
            self.assertIsNone(ua.gap_limit({"loop_gap_limit_s": bad}), bad)


class Gaps(unittest.TestCase):
    def test_regular_spacing_has_no_gap(self):
        g = audit(HOURLY)["loop"]
        self.assertEqual((g["spacing_s"], g["limit_s"]), (H, 3 * H))
        self.assertEqual((g["gaps"], g["open_s"]), ([], None))

    def test_one_gap_of_hours_is_one_loop_down_stretch(self):
        times = without(HOURLY, END - 2 * D, END - 2 * D + 8 * H)
        g = audit(times)["loop"]
        self.assertEqual(len(g["gaps"]), 1)
        self.assertEqual(g["gaps"][0]["s"], 8 * H)
        self.assertEqual(g["gaps"][0]["from"], iso(END - 2 * D))

    def test_a_stretch_at_or_under_the_limit_is_not_a_gap(self):
        times = without(HOURLY, END - 2 * D, END - 2 * D + 3 * H)      # exactly three spacings: not over
        self.assertEqual(audit(times)["loop"]["gaps"], [])

    def test_the_config_limit_replaces_three_spacings(self):
        times = without(HOURLY, END - 2 * D, END - 2 * D + 3 * H)
        g = audit(times, gap_limit=2 * H)["loop"]
        self.assertEqual((g["limit_s"], len(g["gaps"])), (2 * H, 1))

    def test_rows_outside_the_window_are_not_read_for_gaps(self):
        old = [END - 40 * D, END - 35 * D]                              # five days apart, before the window
        self.assertEqual(audit(old + HOURLY)["loop"]["gaps"], [])

    def test_an_open_gap_is_the_newest_run_older_than_the_limit(self):
        self.assertEqual(audit(HOURLY, now=END + 5 * H)["loop"]["open_s"], 5 * H)
        self.assertIsNone(audit(HOURLY, now=END + 2 * H)["loop"]["open_s"])
        self.assertIsNone(audit(HOURLY, now=None)["loop"]["open_s"])   # no clock given: never open

    def test_runs_after_now_are_left_out(self):
        g = audit(HOURLY + [END + 20 * H], now=END + 5 * H)["loop"]
        self.assertEqual((g["open_s"], g["gaps"]), (5 * H, []))

    def test_torn_lines_are_skipped_not_read_as_runs(self):
        good = without(HOURLY, END - 2 * D, END - 2 * D + 8 * H)
        text = "\n".join(json.dumps(r) for r in rows_at(good)) + "\n{\"at\": \"2030-01-1\n{torn\n"
        rows, skipped = ua.parse_lines(text)
        a = ua.audit(rows, days=28, today=TODAY, tz=UTC, now=END + 10 * M, skipped=skipped)
        self.assertEqual((a["skipped"], len(a["loop"]["gaps"])), (2, 1))


if __name__ == "__main__":
    unittest.main()
