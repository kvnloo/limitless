"""sleep.timed_nights and StateReader.sleep_rows spans: when each night ran, per source, for regularity.

Synthetic rows only, UTC as the local zone. A wearable row may carry optional ``start`` and ``end`` (ISO-8601 or
epoch seconds); a valid pair becomes the row's ``span``. The phone's span is the same gap sleep.nights picks.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import sleep  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

UTC = timezone.utc
TODAY = date(2030, 1, 28)
H = 3600


def at(day, hour):
    return datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() + hour * H


def night(ago):
    return TODAY - timedelta(days=ago)


def gap(ago, start_h=23.0, hours=8.0):
    s = at(night(ago), start_h)
    return (s, s + hours * H)


class Rows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        cfg = self.root / "config.json"
        cfg.write_text(json.dumps({"sleep_file": "sleep.jsonl"}))
        self.env = {"LIMITLESS_CONFIG": str(cfg)}

    def rows(self, rows):
        (self.st / "sleep.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        return StateReader(self.st).sleep_rows(TODAY, self.env, self.root)

    def test_a_valid_start_and_end_become_the_span(self):
        base = {"night": "2030-01-26", "asleep_s": 25200, "source": "synthetic-ring"}
        out = self.rows([dict(base, start="2030-01-26T23:00:00Z", end="2030-01-27T07:00:00Z"),
                         dict(base, night="2030-01-25", start=at(night(3), 23), end=at(night(3), 31))])
        self.assertEqual(out[1]["span"], (at(night(2), 23), at(night(2), 31)))
        self.assertEqual(out[0]["span"], (at(night(3), 23), at(night(3), 31)))

    def test_a_bad_span_is_left_out_but_the_row_stays(self):
        base = {"night": "2030-01-26", "asleep_s": 25200, "source": "synthetic-ring"}
        for extra in ({}, {"start": "2030-01-26T23:00:00Z"}, {"start": "x", "end": "y"},
                      {"start": "2030-01-27T07:00:00Z", "end": "2030-01-26T23:00:00Z"},
                      {"start": 0, "end": 2 * 24 * H}, {"start": True, "end": 5}):
            (row,) = self.rows([dict(base, **extra)])
            self.assertEqual(row, base, extra)


class TimedNights(unittest.TestCase):
    def test_spans_per_source_oldest_first_fourteen_by_default(self):
        wear = [{"night": night(2).isoformat(), "asleep_s": 25200, "source": "s",
                 "span": (at(night(2), 23), at(night(2), 31))}, {"night": night(3).isoformat(), "asleep_s": 1,
                                                                   "source": "s"}]
        gaps = [gap(1, 22, 3), gap(1, 23, 8.5), gap(2, 21, 6), gap(20, 23, 8)]
        ns = sleep.timed_nights(wear, gaps, TODAY, tz=UTC)
        self.assertEqual(len(ns), sleep.REGULARITY_DAYS)
        self.assertEqual(sleep.REGULARITY_DAYS, 14)
        self.assertEqual([n["night"] for n in ns], [night(a).isoformat() for a in range(14, 0, -1)])
        by = {n["night"]: n for n in ns}
        self.assertEqual(by[night(1).isoformat()], {"night": night(1).isoformat(), "wearable": None,
                                                    "proxy": gap(1, 23, 8.5)})   # the longest evening gap
        self.assertEqual(by[night(2).isoformat()]["wearable"], (at(night(2), 23), at(night(2), 31)))
        self.assertEqual(by[night(2).isoformat()]["proxy"], gap(2, 21, 6))
        self.assertIsNone(by[night(3).isoformat()]["wearable"])      # a row with no span has no times

    def test_the_proxy_span_is_the_gap_nights_measures(self):
        gaps = [gap(a, 22 + a / 10, 7 + a / 10) for a in range(1, 8)] + [gap(3, 13, 2)]
        timed = {n["night"]: n["proxy"] for n in sleep.timed_nights([], gaps, TODAY, days=7, tz=UTC)}
        for n in sleep.nights([], gaps, TODAY, tz=UTC):
            a, b = timed[n["night"]]
            self.assertEqual(n["proxy"], int(round(b - a)))

    def test_bad_input_is_empty_never_raises(self):
        self.assertEqual(sleep.timed_nights(None, None, "2030-01-28"), [])
        self.assertEqual(sleep.timed_nights([None, {"night": 5}], [None, (1, "x")], TODAY, days=2, tz=UTC),
                         [{"night": night(2).isoformat(), "wearable": None, "proxy": None},
                          {"night": night(1).isoformat(), "wearable": None, "proxy": None}])


if __name__ == "__main__":
    unittest.main()
