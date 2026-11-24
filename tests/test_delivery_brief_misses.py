"""delivery_audit.brief_misses: why the wake brief did not reach the person on a wake day, in words.

Decided only from that day's wake-brief rows in kevin-push's log (``how`` as bin/kevin-push writes it), one
reason a day from a fixed list, with a fixed order of precedence. Synthetic rows, a fixed clock, UTC. Nothing is
written or sent.
"""
from hermetic_env import child_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import delivery_audit as da, jobs, send_gate  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
SLEEP, QUIET, REPEAT, GATE, LOGGED, NONE, UNKNOWN = (
    "held while Sleep mode was on", "held by the quiet setting", "stopped as a repeat",
    "refused by the send gate", "logged but not sent", "no brief attempt on that day", "unknown")


def row(days_ago=0, how="telegram", title="Pick one", hour=9, tag="x"):
    at = int(datetime(TODAY.year, TODAY.month, TODAY.day, hour, tzinfo=UTC).timestamp()) - days_ago * 86400
    return {"at": at, "tag": tag, "cls": "report", "title": title, "body": "Keep the loop?", "how": how}


def brief(days_ago=0, how="telegram", hour=7):
    return row(days_ago, how, title=jobs.WAKE_BRIEF.send_title, hour=hour, tag="limitless")


def wake(*days_ago):
    return [TODAY - timedelta(days=n) for n in days_ago]


def misses(rows, wake_days, **kw):
    return da.brief_misses(rows, wake_days, UTC, **kw)


class FixedList(unittest.TestCase):
    def test_the_reasons_are_the_fixed_list(self):
        self.assertEqual(da.MISS_REASONS, (SLEEP, QUIET, REPEAT, GATE, LOGGED, NONE, UNKNOWN))

    def test_no_reason_has_a_digit(self):
        for r in da.MISS_REASONS:
            self.assertFalse(any(c.isdigit() for c in r), r)


class EachReason(unittest.TestCase):
    CASES = [("held (sleep mode)", SLEEP), ("log (quiet: on)", QUIET), ("log (quiet: snoozed)", QUIET),
             ("log (duplicate)", REPEAT), (f"log ({send_gate.ONCE_DROP})", REPEAT),
             ("log (daily cap)", GATE), ("log (dropped)", GATE),
             ("log", LOGGED), ("folded (brief line)", LOGGED), ("log (telegram rc=1)", LOGGED),
             ("sent by pigeon", UNKNOWN), ("", UNKNOWN)]

    def test_each_how_value_maps_to_its_reason(self):
        for how, reason in self.CASES:
            with self.subTest(how=how):
                out = misses([brief(0, how)], wake(0))
                self.assertEqual(out["days"], {TODAY.isoformat(): reason})
                self.assertEqual(out["missed"], 1)
                self.assertEqual(out["reasons"][reason], 1)

    def test_a_wake_day_with_rows_but_no_brief_row_is_no_brief_attempt(self):
        out = misses([row(0, "telegram"), row(0, "log")], wake(0))
        self.assertEqual(out["days"], {TODAY.isoformat(): NONE})

    def test_other_titles_held_on_that_day_never_lend_their_reason(self):
        out = misses([row(0, "held (sleep mode)"), row(0, "log (quiet: on)")], wake(0))
        self.assertEqual(out["days"], {TODAY.isoformat(): NONE})

    def test_counts_cover_every_reason_with_zero_for_the_unused(self):
        out = misses([brief(0, "held (sleep mode)")], wake(0))
        self.assertEqual(set(out["reasons"]), set(da.MISS_REASONS))
        self.assertEqual(sum(out["reasons"].values()), out["missed"])


class Precedence(unittest.TestCase):
    def test_a_day_with_several_brief_rows_takes_the_highest_reason(self):
        order = [("held (sleep mode)", SLEEP), ("log (quiet: on)", QUIET), ("log (duplicate)", REPEAT),
                 ("log (daily cap)", GATE), ("log", LOGGED), ("odd", UNKNOWN)]
        for i, (top, reason) in enumerate(order):
            rows = [brief(0, h, hour=5 + j) for j, (h, _r) in enumerate(reversed(order[i:]))]
            with self.subTest(top=top):
                self.assertEqual(misses(rows, wake(0))["days"][TODAY.isoformat()], reason)

    def test_precedence_does_not_depend_on_row_order(self):
        a = [brief(0, "log (duplicate)", hour=6), brief(0, "held (sleep mode)", hour=7)]
        self.assertEqual(misses(a, wake(0))["days"], misses(a[::-1], wake(0))["days"])
        self.assertEqual(misses(a, wake(0))["days"][TODAY.isoformat()], SLEEP)

    def test_a_delivered_brief_on_the_same_day_wins_over_any_held_row(self):
        rows = [brief(0, "held (sleep mode)", hour=6), brief(0, "log (quiet: on)", hour=6),
                brief(0, "telegram", hour=8), brief(0, "log (duplicate)", hour=9)]
        out = misses(rows, wake(0))
        self.assertEqual(out["missed"], 0)
        self.assertEqual(out["days"], {})
        self.assertEqual(sum(out["reasons"].values()), 0)

    def test_each_day_is_judged_from_its_own_rows_only(self):
        rows = [brief(1, "held (sleep mode)"), row(0, "log")]
        out = misses(rows, wake(0, 1))
        self.assertEqual(out["days"], {TODAY.isoformat(): NONE,
                                       (TODAY - timedelta(days=1)).isoformat(): SLEEP})

    def test_the_local_day_follows_tz(self):
        plus = timezone(timedelta(hours=5))
        r = brief(0, "held (sleep mode)", hour=22)          # the next local day five hours east
        nxt = TODAY + timedelta(days=1)
        self.assertEqual(da.brief_misses([r, row(0, "log", hour=23)], [nxt], plus)["days"],
                         {nxt.isoformat(): SLEEP})


class Unknown(unittest.TestCase):
    def test_a_wake_day_with_no_row_at_all_is_never_counted_as_missed(self):
        out = misses([brief(0, "held (sleep mode)")], wake(0, 2, 3))
        self.assertEqual(out["missed"], 1)
        self.assertEqual(out["unknown_wake_days"], 2)
        self.assertNotIn((TODAY - timedelta(days=2)).isoformat(), out["days"])

    def test_a_day_that_is_not_a_wake_day_is_never_a_miss(self):
        out = misses([brief(1, "held (sleep mode)"), row(0)], wake(0))
        self.assertEqual(out["days"], {TODAY.isoformat(): NONE})

    def test_an_empty_log_is_unknown(self):
        for rows in ([], None):
            out = misses(rows, wake(0, 1))
            self.assertFalse(out["known"])
            self.assertEqual(out["missed"], 0)
            self.assertEqual(out["days"], {})

    def test_no_known_wake_days_is_unknown(self):
        for wd in (None, []):
            out = misses([brief(0, "held (sleep mode)")], wd)
            self.assertFalse(out["known"])
            self.assertEqual(out["days"], {})

    def test_bad_rows_are_skipped_not_judged(self):
        out = misses([{"at": "soon", "how": "held (sleep mode)", "title": jobs.WAKE_BRIEF.send_title},
                      row(0, "log")], wake(0))
        self.assertEqual(out["days"], {TODAY.isoformat(): NONE})

    def test_days_limits_the_judged_days(self):
        rows = [brief(0, "log"), brief(9, "log")]
        out = misses(rows, wake(0, 9), days={TODAY})
        self.assertEqual(list(out["days"]), [TODAY.isoformat()])

    def test_iso_strings_are_wake_days_too(self):
        out = misses([brief(0, "log")], [TODAY.isoformat()])
        self.assertEqual(out["days"], {TODAY.isoformat(): LOGGED})


if __name__ == "__main__":
    unittest.main()
