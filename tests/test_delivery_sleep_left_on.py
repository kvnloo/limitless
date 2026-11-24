"""delivery_audit: a wake brief held while Sleep mode was left on is its own miss reason.

kevin-push logs "held (sleep mode)" for every push it holds while sleepmode.jsonl's last row is on. When the
poller later closes that activation with an inferred off row carrying ``left_on`` (a phone Sleep rule left on far
longer than a night, closed once the owner was seen up), the brief was not held by a night: the reason is "held
while Sleep mode was left on". No sleepmode.jsonl, or one without such a row, keeps the old reason. Synthetic
kevin-push logs and sleepmode.jsonl files, a fixed clock, UTC. Nothing is written or sent.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import delivery_audit as da, doctor, jobs, sleepmode, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_delivery_brief_misses_wiring import Missed  # noqa: E402
from test_scorecard_measured import NOW as WNOW  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
H = 3600.0
SLEEP, LEFT_ON = "held while Sleep mode was on", "held while Sleep mode was left on"
DIGIT = re.compile(r"\d")
INFERRED = {"on": False, "inferred": "Sleep left on, owner up"}


def at(days_ago=0, hour=7):
    return datetime(TODAY.year, TODAY.month, TODAY.day, hour, tzinfo=UTC).timestamp() - days_ago * 86400


def brief(days_ago=0, how="held (sleep mode)", hour=7):
    return {"at": int(at(days_ago, hour)), "tag": "limitless", "cls": "report", "title": jobs.WAKE_BRIEF.send_title,
            "body": "Morning", "how": how}


def sm(*rows):
    """sleepmode.parse of synthetic rows (``at`` as ISO-8601, the poller's form)."""
    text = "".join(json.dumps(dict(r, at=datetime.fromtimestamp(r["at"], UTC).isoformat())) + "\n" for r in rows)
    return sleepmode.parse(text)


def misses(rows, wake_days, sleep):
    return da.brief_misses(rows, wake_days, UTC, sleep=sleep)


class TheWord(unittest.TestCase):
    def test_the_new_reason_comes_right_after_the_sleep_reason(self):
        self.assertEqual(da.MISS_LEFT_ON, LEFT_ON)
        self.assertEqual(da.MISS_REASONS.index(LEFT_ON), da.MISS_REASONS.index(SLEEP) + 1)
        self.assertEqual(da.MISS_ORDER.index(LEFT_ON), da.MISS_ORDER.index(SLEEP) + 1)
        self.assertIsNone(DIGIT.search(LEFT_ON))


class Activation(unittest.TestCase):
    LEFT = sm({"at": at(2, 22), "on": True, "rule": "rule-a"}, dict(INFERRED, at=at(0, 10), left_on="rule-a"))

    def test_a_hold_in_an_activation_later_closed_as_left_on(self):
        out = misses([brief(0)], [TODAY], self.LEFT)
        self.assertEqual(out["days"], {TODAY.isoformat(): LEFT_ON})
        self.assertEqual(out["reasons"][LEFT_ON], 1)
        self.assertEqual(out["reasons"][SLEEP], 0)
        self.assertEqual(out["label"], "missed wake briefs: held while Sleep mode was left on (all)")

    def test_every_held_day_of_one_long_activation_is_left_on(self):
        out = misses([brief(1), brief(0)], [TODAY - timedelta(days=1), TODAY], self.LEFT)
        self.assertEqual(set(out["days"].values()), {LEFT_ON})
        self.assertEqual(out["top"], LEFT_ON)

    def test_a_plain_off_close_keeps_the_sleep_reason(self):
        plain = sm({"at": at(1, 22), "on": True, "rule": "rule-a"}, {"at": at(0, 8), "on": False})
        self.assertEqual(misses([brief(0)], [TODAY], plain)["days"], {TODAY.isoformat(): SLEEP})

    def test_an_activation_not_closed_yet_keeps_the_sleep_reason(self):
        still = sm({"at": at(2, 22), "on": True, "rule": "rule-a"})
        self.assertEqual(misses([brief(0)], [TODAY], still)["days"], {TODAY.isoformat(): SLEEP})

    def test_old_rows_without_rule_or_left_on_keep_the_sleep_reason(self):
        old = sm({"at": at(1, 22), "on": True}, {"at": at(0, 8), "on": False})
        self.assertEqual(misses([brief(0)], [TODAY], old)["days"], {TODAY.isoformat(): SLEEP})

    def test_a_left_on_close_of_an_earlier_activation_does_not_lend_its_reason(self):
        rows = sm({"at": at(3, 22), "on": True, "rule": "rule-a"}, dict(INFERRED, at=at(1, 10), left_on="rule-a"),
                  {"at": at(1, 23), "on": True, "rule": "rule-b"}, {"at": at(0, 8), "on": False})
        self.assertEqual(misses([brief(0)], [TODAY], rows)["days"], {TODAY.isoformat(): SLEEP})

    def test_a_hold_before_any_on_row_keeps_the_sleep_reason(self):
        rows = sm({"at": at(0, 9), "on": True}, dict(INFERRED, at=at(0, 11), left_on="rule-a"))
        self.assertEqual(misses([brief(0, hour=7)], [TODAY], rows)["days"], {TODAY.isoformat(): SLEEP})

    def test_repeated_on_rows_are_one_activation(self):
        rows = sm({"at": at(2, 22), "on": True, "rule": "rule-a"}, {"at": at(1, 22), "on": True, "rule": "rule-a"},
                  dict(INFERRED, at=at(0, 10), left_on="rule-a"))
        self.assertEqual(misses([brief(0)], [TODAY], rows)["days"], {TODAY.isoformat(): LEFT_ON})

    def test_no_sleep_rows_is_todays_behaviour(self):
        for sleep in (None, []):
            with self.subTest(sleep=sleep):
                self.assertEqual(misses([brief(0)], [TODAY], sleep)["days"], {TODAY.isoformat(): SLEEP})
        self.assertEqual(da.brief_misses([brief(0)], [TODAY], UTC)["days"], {TODAY.isoformat(): SLEEP})

    def test_other_reasons_are_untouched(self):
        out = misses([brief(0, "log (quiet: on)")], [TODAY], self.LEFT)
        self.assertEqual(out["days"], {TODAY.isoformat(): da.MISS_QUIET})

    def test_a_sleep_hold_and_a_left_on_hold_on_one_day_is_the_sleep_reason(self):
        rows = sm({"at": at(0, 1), "on": True}, {"at": at(0, 5), "on": False},
                  {"at": at(0, 6), "on": True, "rule": "rule-a"}, dict(INFERRED, at=at(0, 10), left_on="rule-a"))
        out = misses([brief(0, hour=3), brief(0, hour=7)], [TODAY], rows)
        self.assertEqual(out["days"], {TODAY.isoformat(): SLEEP})


class InTheAudit(unittest.TestCase):
    def test_audit_passes_the_rows_and_the_clause_names_the_new_reason(self):
        a = da.audit([brief(0)], wake_days=[TODAY], today=TODAY, tz=UTC, sleep=Activation.LEFT)
        self.assertEqual(a["misses"]["days"], {TODAY.isoformat(): LEFT_ON})
        self.assertEqual(da.miss_clause(a), "most common miss: held while Sleep mode was left on")


class Reading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name)

    def test_an_absent_file_is_none(self):
        self.assertIsNone(da.sleep_rows(self.st, env={}))

    def test_the_file_is_read_from_the_state_dir_or_limitless_sleepmode_and_left_as_it_is(self):
        p = self.st / "sleepmode.jsonl"
        p.write_text(json.dumps({"at": at(0, 8), "on": False, "left_on": "rule-a"}) + "\n")
        before = (p.read_bytes(), p.stat().st_mtime_ns)
        got = da.sleep_rows(self.st, env={})
        self.assertEqual(len(got), 1)
        self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), before)
        other = self.st / "elsewhere.jsonl"
        other.write_text(json.dumps({"at": at(0, 8), "on": True}) + "\n")
        self.assertTrue(da.sleep_rows(self.st, env={"LIMITLESS_SLEEPMODE": str(other)})[0][1]["on"])


class Wired(Missed):
    """The tool, the doctor's delivery row and the scorecard read sleepmode.jsonl from the state dir."""

    def left_on_week(self):
        self.week(held=(0, 1, 2))
        log = [json.loads(ln) for ln in (self.st / "push-log.jsonl").read_text().splitlines()]
        held = sorted(r["at"] for r in log if r["how"] == "held (sleep mode)")
        rows = [{"at": held[0] - 3 * H, "on": True, "rule": "rule-a"},
                dict(INFERRED, at=held[-1] + 2 * H, left_on="rule-a")]
        (self.st / "sleepmode.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def test_the_tool_and_the_doctor_name_the_left_on_reason(self):
        self.left_on_week()
        res = self.tool(raw=True)
        self.assertTrue(res["label"]["label"].endswith("; most common miss: held while Sleep mode was left on"),
                        res["label"])
        self.assertEqual(res["value"]["misses"]["reasons"][LEFT_ON], 3)
        r = self.doctor_row()
        self.assertEqual(r["status"], doctor.STALE)
        self.assertTrue(r["reason"].endswith("; most common miss: held while Sleep mode was left on"), r)
        self.assertNotIn("rule-a", json.dumps(res) + json.dumps(r))

    def test_without_the_file_the_reason_is_unchanged(self):
        self.week(held=(0, 1, 2))
        self.assertFalse((self.st / "sleepmode.jsonl").exists())
        self.assertTrue(self.tool()["label"]["label"].endswith("; most common miss: held while Sleep mode was on"))

    def test_the_scorecard_counts_the_same_misses(self):
        from limitless import scorecard as sc
        self.left_on_week()
        _, goal, a = sc._delivery_measured(self.st, self.cfg, WNOW, UTC, None, self.root)
        self.assertEqual(goal, da.GOAL_NOT_MET)
        self.assertEqual(a["misses"]["reasons"][LEFT_ON], 3)


class Docs(unittest.TestCase):
    def test_the_doc_explains_the_left_on_reason_and_its_example_shows_it(self):
        text = (ROOT / "docs" / "delivery-audit.md").read_text()
        section = text.split("## Why a wake brief was missed", 1)[1].split("\n## ", 1)[0]
        for words in (LEFT_ON, '"left_on"', "sleep_rows", "LIMITLESS_SLEEPMODE", "read-only", "changes\n  nothing"):
            self.assertIn(words, section)
        run = text.split("## A real synthetic run", 1)[1]
        self.assertIn("held while Sleep mode was left on (some)", run)


if __name__ == "__main__":
    unittest.main()
