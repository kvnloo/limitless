"""The week review's body line (body.review_line, digit-free) beside the flow line; the card gets none.

Synthetic rows only, a fake push, a fixed clock.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import card, jobs, jobs_runner  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_flow_week_hooks import FakePush, noon, write_db  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
FIX = ROOT / "tests" / "fixtures" / "state"


def body_rows(prior=(22.0, 22.1, 21.9), recent=(21.0, 21.1, 20.9), calibrated=True):
    days = [27, 24, 21][:len(prior)] + [10, 6, 2][:len(recent)]
    return [{"day": (TODAY - timedelta(days=d)).isoformat(), "bf_pct": v, "method": "synthetic-scale",
             "calibrated": calibrated} for d, v in zip(days, list(prior) + list(recent))]


class Review(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}
        self.week_of = TODAY - timedelta(days=6)
        self.habit = {"week_of": self.week_of.isoformat(), "habit": "Synthetic habit",
                      "checkins": {self.week_of.isoformat(): "Done"}}
        (self.st / "habit.json").write_text(json.dumps(self.habit))
        (self.st / "events.jsonl").write_text(json.dumps({"event": "habit_cue", "at": NOW - 60}) + "\n")

    def configure(self, **cfg):
        self.cfg.write_text(json.dumps(cfg))

    def write_body(self, rows):
        (self.st / "body.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def review(self):
        push = FakePush()
        rows = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=self.env, home=self.root, tz=UTC)
        self.assertEqual({r["job"]: r for r in rows}["Week review"]["action"], jobs.DELIVER)
        (text,) = [c[1] for c in push.calls if c[0] == "Week review"]
        return text.split("\n")

    def test_body_puts_the_body_line_after_the_flow_line(self):
        text = jobs.week_review_text(self.habit)
        self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, self.habit, flow="Flow: x.", body_line="Body: y."),
                         text + "\nFlow: x.\nBody: y.")
        self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, self.habit, body_line=""), text)
        self.assertNotIn("Body", jobs_runner.body(jobs.HABIT_CHECKIN, self.habit, body_line="Body: y."))

    def test_the_review_carries_the_trend_words(self):
        self.configure(body_file="body.jsonl")
        self.write_body(body_rows())
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit),
                                         "Body fat trending down (calibrated estimate)."])

    def test_uncalibrated_and_not_enough(self):
        self.configure(body_file="body.jsonl")
        self.write_body(body_rows(calibrated=False, recent=(22.0, 22.2, 21.9)))
        self.assertEqual(self.review()[-1], "Body fat trending flat (uncalibrated estimate).")
        self.write_body(body_rows(prior=(22.0,)))
        (self.st / "jobs-sent.jsonl").unlink()
        self.assertEqual(self.review()[-1], "Body fat: not enough measurements.")

    def test_beside_the_flow_line_and_digit_free(self):
        write_db(self.st / "aw.db", [(noon(self.week_of), noon(self.week_of) + 3600, "editor")])
        self.configure(body_file="body.jsonl", aw_db="aw.db", flow_work_apps=["editor"])
        self.write_body(body_rows())
        lines = self.review()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[1].startswith("Flow ("), lines)
        self.assertEqual(lines[2], "Body fat trending down (calibrated estimate).")
        self.assertEqual(re.findall(r"\d", lines[2]), [])

    def test_no_body_file_or_no_rows_leaves_the_review_unchanged(self):
        self.write_body(body_rows())
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit)])
        self.configure(body_file="absent.jsonl")
        (self.st / "jobs-sent.jsonl").unlink()
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit)])

    def test_week_body_helper(self):
        self.configure(body_file="body.jsonl")
        self.write_body(body_rows())
        self.assertEqual(jobs_runner.week_body(self.st, self.env, self.root, TODAY),
                         "Body fat trending down (calibrated estimate).")
        self.configure()
        self.assertEqual(jobs_runner.week_body(self.st, self.env, self.root, TODAY), "")

    def test_the_body_file_is_never_written(self):
        self.configure(body_file="body.jsonl")
        self.write_body(body_rows())
        p = self.st / "body.jsonl"
        before = (p.read_bytes(), p.stat().st_mtime_ns)
        self.review()
        self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), before)


class CardHasNoBodyLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name) / "st"
        shutil.copytree(FIX, self.st)
        self.cfg = Path(self.tmp.name) / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}

    def build(self, raw=False):
        now = 1894708800.0
        today = datetime.fromtimestamp(now).date()
        return card.build(StateReader(self.st), now, today, raw=raw, env=self.env, owner={"value": None})["lines"]

    def test_the_card_is_the_same_with_a_body_file(self):
        before = self.build()
        today = datetime.fromtimestamp(1894708800.0).date()
        rows = [{"day": (today - timedelta(days=d)).isoformat(), "bf_pct": 20.0 + d / 10, "method": "synthetic",
                 "calibrated": True} for d in (1, 4, 7, 15, 18, 21)]
        (self.st / "body.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.cfg.write_text(json.dumps({"body_file": "body.jsonl"}))
        for raw in (False, True):
            lines = self.build(raw)
            self.assertEqual(len(lines), len(before))
            self.assertNotIn("body", "\n".join(lines).lower())
        self.assertEqual(self.build(), before)


if __name__ == "__main__":
    unittest.main()
