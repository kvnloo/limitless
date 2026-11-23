"""The feed-reflex line in the week review (jobs_runner.week_feed_reflex / body / run_once).

One optional, digit-free line through tier_audit.gate (hook week_review:feed_reflex); nothing when unknown.
Synthetic ActivityWatch DB (made-up app names), a fake push, a fixed clock, UTC. No new job, no new push.
"""
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from limitless import feed_reflex, jobs, jobs_runner, weekly_target  # noqa: E402
from test_aw_reader import make_db  # noqa: E402
from test_flow_week_hooks import FakePush  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
KD = "\nReply: Keep / Drop"
OFTEN_LINE = "Phone: a feed was often the first thing opened after unlocking this week."


def spans(n=6, feed=4):
    unlocks = [NOW - (i + 2) * 3600.0 for i in range(n)]
    return unlocks, [(u + 2, u + 300, "feedapp" if i < feed else "notes") for i, u in enumerate(unlocks)]


class State(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.audit = self.root / "audit.jsonl"
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_AUDIT": str(self.audit)}
        self.week_of = TODAY - timedelta(days=6)
        self.habit = {"week_of": self.week_of.isoformat(), "habit": "Synthetic habit",
                      "checkins": {self.week_of.isoformat(): "Done"}}
        (self.st / "habit.json").write_text(json.dumps(self.habit))
        (self.st / "events.jsonl").write_text(json.dumps({"event": "habit_cue", "at": NOW - 60}) + "\n")
        self.cfg.write_text("{}")

    def reflex(self, n=6, feed=4, **cfg):
        name = f"aw-{n}-{feed}.db"   # a fresh synthetic DB per shape
        make_db(self.st / name, *spans(n, feed))
        self.cfg.write_text(json.dumps(dict({"aw_db": name, "feed_apps": ["feedapp"]}, **cfg)))

    def line(self):
        return jobs_runner.week_feed_reflex(self.st, self.habit, self.env, self.root, UTC)

    def audited(self):
        return [json.loads(ln) for ln in self.audit.read_text().splitlines()] if self.audit.exists() else []

    def review(self):
        push = FakePush()
        out = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=self.env, home=self.root, tz=UTC)
        self.assertEqual({r["job"]: r for r in out}["Week review"]["action"], jobs.DELIVER, out)
        (text,) = [c[1] for c in push.calls if c[0] == "Week review"]
        self.assertTrue(text.endswith(KD), text)
        return text[:-len(KD)].split("\n")


class Helper(State):
    def test_known_words(self):
        self.reflex()
        self.assertEqual(self.line(), OFTEN_LINE)
        self.reflex(feed=0)
        self.assertEqual(self.line(), "Phone: a feed was rarely the first thing opened after unlocking this week.")

    def test_unknown_is_nothing(self):
        self.assertEqual(self.line(), "")                       # nothing set
        make_db(self.st / "aw.db", *spans())
        self.cfg.write_text(json.dumps({"aw_db": "aw.db"}))
        self.assertEqual(self.line(), "")                       # no feed apps
        self.reflex(n=2, feed=2)
        self.assertEqual(self.line(), "")                       # too few unlocks
        self.assertEqual(jobs_runner.week_feed_reflex(self.st, None, self.env, self.root, UTC), "")   # no week

    def test_the_line_passes_the_tier_audit_gate(self):
        self.reflex()
        self.line()
        (row,) = self.audited()
        self.assertEqual((row["hook"], row["tier"], row["blocked"]), ("week_review:feed_reflex", "T1", False))

    def test_a_digit_is_blocked_by_the_gate(self):
        self.reflex()
        with mock.patch.object(feed_reflex, "review_line", return_value="Phone: four of six unlocks, 4/6."):
            self.assertEqual(self.line(), "")
        self.assertTrue(self.audited()[-1]["blocked"])

    def test_a_broken_db_does_not_stop_the_review(self):
        self.cfg.write_text(json.dumps({"aw_db": "aw.db", "feed_apps": ["feedapp"]}))
        (self.st / "aw.db").write_bytes(b"not a database")
        self.assertEqual(self.line(), "")


class Body(State):
    def test_the_line_sits_right_after_the_flow_metrics_line(self):
        text = jobs_runner.body(jobs.WEEK_REVIEW, self.habit, fragment="Work: f.", body_line="Body: b.",
                                reflex_line=OFTEN_LINE)
        lines = text.split("\n")
        self.assertEqual(lines[lines.index("Work: f."):][:3], ["Work: f.", OFTEN_LINE, "Body: b."])

    def test_only_the_week_review_carries_it(self):
        for spec in (jobs.HABIT_CHECKIN, jobs.MIQ):
            self.assertNotIn("unlocking", jobs_runner.body(spec, self.habit, reflex_line=OFTEN_LINE))


class Review(State):
    def test_the_review_carries_the_words(self):
        self.reflex()
        lines = self.review()
        self.assertIn(OFTEN_LINE, lines)
        self.assertEqual(re.findall(r"\d", OFTEN_LINE), [])
        self.assertIn("week_review:feed_reflex", [r["hook"] for r in self.audited()])

    def test_nothing_set_leaves_the_review_unchanged(self):
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit), weekly_target.REVIEW_ON_THE_WAY])


if __name__ == "__main__":
    unittest.main()
