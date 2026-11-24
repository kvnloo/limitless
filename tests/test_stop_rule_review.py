"""The week review's stop-rule line: "Your rule says: keep it" / "drop it" / "your call", digit-free, through
tier_audit.gate, last before "Reply: Keep / Drop"; no line when the verdict is unknown or no rule was set.
The rule only suggests: the reply decides. Synthetic data, a fake push, a fixed clock."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import jobs, jobs_runner, stop_rule, weekly_target  # noqa: E402
from test_flow_week_hooks import FakePush  # noqa: E402

KD = "Reply: Keep / Drop"
UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
BANNED = re.compile(r"(?i)\d|streak|missed|failed|\bmust\b|\bshould\b|\b(am|pm)\b|o'clock")


class Line(unittest.TestCase):
    def test_the_three_lines_and_nothing_for_unknown(self):
        self.assertEqual(stop_rule.review_line("keep"), "Your rule says: keep it")
        self.assertEqual(stop_rule.review_line("drop"), "Your rule says: drop it")
        self.assertEqual(stop_rule.review_line("your call"), "Your rule says: your call")
        for v in ("unknown", None, "", "maybe", "Keep"):
            self.assertEqual(stop_rule.review_line(v), "", v)

    def test_lines_are_digit_free_and_soft(self):
        for v in stop_rule.VERDICTS:
            self.assertIsNone(BANNED.search(stop_rule.review_line(v)), v)

    def test_body_puts_the_rule_line_last_before_the_choices(self):
        h = {"habit": "Synthetic habit", "week_of": (TODAY - timedelta(days=6)).isoformat(), "checkins": {}}
        got = jobs_runner.body(jobs.WEEK_REVIEW, h, anki_line="Anki: a.", rule_line="Your rule says: keep it")
        self.assertEqual(got.splitlines()[-3:], ["Anki: a.", "Your rule says: keep it", KD])
        self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, h), jobs.week_review_text(h) + "\n" + KD)
        self.assertNotIn("rule", jobs_runner.body(jobs.HABIT_CHECKIN, h, rule_line="Your rule says: keep it"))


class Review(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.audit = self.root / "audit.jsonl"
        self.env = {"LIMITLESS_CONFIG": str(self.root / "none.json"), "LIMITLESS_AUDIT": str(self.audit)}
        self.week_of = TODAY - timedelta(days=6)
        (self.st / "events.jsonl").write_text(json.dumps({"event": "habit_cue", "at": NOW - 60}) + "\n")

    def habit(self, rule, *answers):
        h = {"habit": "Synthetic habit", "week_of": self.week_of.isoformat(),
             "checkins": {(self.week_of + timedelta(days=i)).isoformat(): a for i, a in enumerate(answers)}}
        if rule:
            h["stop_rule"] = rule
        (self.st / "habit.json").write_text(json.dumps(h))
        return h

    def review(self):
        push = FakePush()
        rows = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=self.env, home=self.root, tz=UTC)
        self.assertEqual({r["job"]: r for r in rows}["Week review"]["action"], jobs.DELIVER)
        (text,) = [c[1] for c in push.calls if c[0] == "Week review"]
        return text.split("\n")

    def test_the_review_says_what_the_rule_says_then_asks(self):
        self.habit("most_done", "Done", "Done", "No", "Skipped")
        lines = self.review()
        self.assertEqual(lines[-2:], ["Your rule says: keep it", KD])
        hooks = [json.loads(ln)["hook"] for ln in self.audit.read_text().splitlines()]
        self.assertIn("week_review:stop_rule", hooks)

    def test_drop_and_your_call(self):
        self.habit("any_done", "No", "No")
        self.assertEqual(self.review()[-2:], ["Your rule says: drop it", KD])
        (self.st / "jobs-sent.jsonl").unlink()
        self.habit("no_rule", "No")
        self.assertEqual(self.review()[-2:], ["Your rule says: your call", KD])

    def test_unknown_or_no_rule_leaves_the_review_as_before(self):
        h = self.habit("most_done", "Skipped", "Skipped")
        self.assertEqual(self.review(), [jobs.week_review_text(h), KD])
        (self.st / "jobs-sent.jsonl").unlink()
        h = self.habit(None, "Done")
        self.assertEqual(self.review(), [jobs.week_review_text(h), weekly_target.REVIEW_ON_THE_WAY, KD])

    def test_week_rule_is_gated_and_reads_only(self):
        self.habit("most_done", "Done")
        before = sorted(p.name for p in self.st.iterdir())
        h = json.loads((self.st / "habit.json").read_text())
        self.assertEqual(jobs_runner.week_rule(h, None, self.env, self.root), "Your rule says: keep it")
        self.assertEqual(jobs_runner.week_rule(None, None, self.env, self.root), "")
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), before)

    def test_the_review_never_writes_a_decision(self):
        self.habit("any_done", "No")
        self.review()
        self.assertNotIn("decision", json.loads((self.st / "habit.json").read_text()))


if __name__ == "__main__":
    unittest.main()
