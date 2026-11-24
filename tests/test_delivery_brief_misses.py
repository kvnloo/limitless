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
        self.assertEqual(da.MISS_REASONS, (SLEEP, da.MISS_LEFT_ON, QUIET, REPEAT, GATE, LOGGED, NONE, UNKNOWN))

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


class Words(unittest.TestCase):
    def test_label_names_each_reason_with_a_share_word_most_first(self):
        rows = [brief(0, "held (sleep mode)"), brief(1, "held (sleep mode)"), row(2, "log")]
        out = misses(rows, wake(0, 1, 2))
        self.assertEqual(out["label"], "missed wake briefs: held while Sleep mode was on (most), "
                                       "no brief attempt on that day (some)")

    def test_one_reason_for_every_miss_is_all(self):
        out = misses([brief(0, "log (quiet: on)")], wake(0))
        self.assertEqual(out["label"], "missed wake briefs: held by the quiet setting (all)")

    def test_an_even_split_is_some_each_in_list_order(self):
        out = misses([brief(0, "log (duplicate)"), brief(1, "held (sleep mode)")], wake(0, 1))
        self.assertEqual(out["label"], "missed wake briefs: held while Sleep mode was on (some), "
                                       "stopped as a repeat (some)")
        self.assertEqual(out["top"], SLEEP)

    def test_no_miss_and_unknown_have_their_own_words(self):
        self.assertEqual(misses([brief(0)], wake(0))["label"], da.MISSES_NONE)
        self.assertEqual(misses([], wake(0))["label"], da.MISSES_UNKNOWN)
        self.assertEqual(misses([brief(0, "log")], None)["label"], da.MISSES_UNKNOWN)

    def test_labels_never_hold_a_digit_a_date_or_a_clock_time(self):
        rows = [brief(n, h) for n, h in enumerate(["held (sleep mode)", "log (quiet: on)", "log (duplicate)",
                                                   "log (daily cap)", "log (telegram rc=2)", "odd"])] + [row(6)]
        rows.append(brief(7, "held (sleep mode)"))      # held in an activation the poller closed as left on
        on, off = brief(7, hour=1)["at"], brief(7, hour=9)["at"]
        sleep = [(on, {"at": on, "on": True, "rule": "rule-a"}),
                 (off, {"at": off, "on": False, "inferred": "Sleep left on, owner up", "left_on": "rule-a"})]
        out = misses(rows, wake(*range(8)), sleep=sleep)
        self.assertEqual(out["missed"], 8)
        for label in (out["label"], da.MISSES_NONE, da.MISSES_UNKNOWN):
            self.assertFalse(any(c.isdigit() for c in label), label)
            self.assertNotIn(":0", label)
        for r in da.MISS_REASONS:
            self.assertIn(r, out["label"])


class InTheAudit(unittest.TestCase):
    def test_audit_keeps_the_misses_of_its_window_and_they_add_up(self):
        rows = [brief(0), brief(1, "held (sleep mode)"), row(2, "log"), brief(9, "log")]
        a = da.audit(rows, wake_days=wake(0, 1, 2, 3, 9), today=TODAY, tz=UTC)
        m = a["misses"]
        self.assertEqual(m["missed"], a["wake"]["wake_days"] - a["wake"]["brief_delivered"])
        self.assertEqual(m["reasons"][SLEEP], 1)
        self.assertEqual(m["reasons"][NONE], 1)
        self.assertEqual(m["unknown_wake_days"], a["wake"]["unknown_wake_days"])
        self.assertNotIn((TODAY - timedelta(days=9)).isoformat(), m["days"])

    def test_the_audits_label_is_unchanged_by_the_misses(self):
        rows = [brief(0, "held (sleep mode)")]
        a = da.audit(rows, wake_days=wake(0), today=TODAY, tz=UTC)
        self.assertNotIn("misses", a["labels"])
        self.assertNotIn(SLEEP, a["label"]["label"])

    def test_miss_clause_only_when_the_goal_is_not_met(self):
        missed = da.audit([brief(0, "held (sleep mode)")], wake_days=wake(0), today=TODAY, tz=UTC)
        self.assertEqual(da.goal(missed), da.GOAL_NOT_MET)
        self.assertEqual(da.miss_clause(missed), "most common miss: held while Sleep mode was on")
        fine = da.audit([brief(0)], wake_days=wake(0), today=TODAY, tz=UTC)
        self.assertEqual(da.miss_clause(fine), "")
        over = da.audit([row(0)] * 9 + [brief(0)], wake_days=wake(0), today=TODAY, tz=UTC)
        self.assertEqual(da.goal(over), da.GOAL_NOT_MET)
        self.assertEqual(da.miss_clause(over), "")          # not met for another reason: no brief missed
        for a in (None, {}, da.audit([], wake_days=wake(0), today=TODAY, tz=UTC)):
            self.assertEqual(da.miss_clause(a), "")


class Docs(unittest.TestCase):
    def test_the_doc_has_the_section_with_every_reason_and_the_precedence(self):
        text = (ROOT / "docs" / "delivery-audit.md").read_text()
        self.assertIn("## Why a wake brief was missed", text)
        section = text.split("## Why a wake brief was missed", 1)[1].split("\n## ", 1)[0]
        for word in da.MISS_REASONS + ("precedence", "most common miss", "brief_misses", "miss_clause",
                                       '"held (sleep mode)"', '"log (quiet: ...)"', "unknown, not zero"):
            self.assertIn(word, section)
        self.assertIn('"misses"', text)
        for word in ("missed wake briefs:", "most common miss: held while Sleep mode was on"):
            self.assertIn(word, text.split("## A real synthetic run", 1)[1])


if __name__ == "__main__":
    unittest.main()
