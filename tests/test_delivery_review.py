"""The delivery audit's one line in the week review (jobs_runner.week_delivery / body / week_review_body).

At most one line, "Pushes: <words>.", through tier_audit.gate (hook week_review:delivery); nothing when the
push log is unset, unreadable or has no row in the week (unknown, not zero). Synthetic rows in bin/kevin-push's
log shape, a fake push, a fixed clock, UTC. No new job and no new push.
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

from limitless import delivery_audit, jobs, jobs_runner, weekly_target  # noqa: E402
from test_flow_week_hooks import FakePush  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
KD = "\nReply: Keep / Drop"
H = 3600


def row(at, how="telegram", title="Pick one", body="Keep it?\nReply: Yes / No\nWhy now: you woke up"):
    return {"at": int(at), "tag": "x", "cls": "decision", "title": title, "body": body, "how": how}


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
        week_of = TODAY - timedelta(days=6)
        self.habit = {"week_of": week_of.isoformat(), "habit": "Synthetic habit",
                      "checkins": {week_of.isoformat(): "Done"}}
        (self.st / "habit.json").write_text(json.dumps(self.habit))
        (self.st / "events.jsonl").write_text(
            json.dumps({"event": "wake", "at": NOW - 5 * H}) + "\n"
            + json.dumps({"event": "habit_cue", "at": NOW - 60}) + "\n")

    def log(self, rows, cfg=None):
        p = self.st / "push-log.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.cfg.write_text(json.dumps(dict({"push_log": "push-log.jsonl"}, **(cfg or {}))))
        return p

    def line(self):
        return jobs_runner.week_delivery(self.st, self.env, self.root, TODAY, UTC, NOW)

    def audited(self):
        return [json.loads(ln) for ln in self.audit.read_text().splitlines()] if self.audit.exists() else []

    def review(self):
        push = FakePush()
        out = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=self.env, home=self.root, tz=UTC)
        self.assertEqual({r["job"]: r for r in out}["Week review"]["action"], jobs.DELIVER, out)
        (text,) = [c[1] for c in push.calls if c[0] == "Week review"]
        self.assertTrue(text.endswith(KD), text)
        return text[:-len(KD)].split("\n")


class Body(State):
    def test_the_line_sits_after_the_ideas_line(self):
        text = jobs_runner.body(jobs.WEEK_REVIEW, self.habit, ideas_line="Ideas: i.", rule_line="Your rule says: r.",
                                delivery_line="Pushes: p.")
        self.assertEqual(text.split("\n")[-4:-1], ["Ideas: i.", "Pushes: p.", "Your rule says: r."])

    def test_only_the_week_review_carries_it(self):
        for spec in (jobs.HABIT_CHECKIN, jobs.MIQ, jobs.WAKE_BRIEF):
            self.assertNotIn("Pushes", jobs_runner.body(spec, self.habit, delivery_line="Pushes: p."))


class Helper(State):
    def test_words_from_the_log(self):
        self.log([row(NOW - 4 * H, title=jobs.WAKE_BRIEF.send_title, body="Good morning.\nWhy now: you woke up"),
                  row(NOW - 3 * H),
                  row(NOW - 2 * H, how="held (sleep mode)")])
        line = self.line()
        self.assertEqual(line, "Pushes: within the push limit on every logged day; brief reached you on every wake "
                               "day; some pushes had no reply line.")
        self.assertEqual(re.findall(r"\d", line), [])
        (r,) = self.audited()
        self.assertEqual((r["hook"], r["tier"], r["blocked"]), ("week_review:delivery", "T1", False))

    def test_unknown_brief_words_are_left_out(self):
        (self.st / "events.jsonl").write_text(json.dumps({"event": "habit_cue", "at": NOW - 60}) + "\n")
        self.log([row(NOW - 3 * H)])
        self.assertEqual(self.line(), "Pushes: within the push limit on every logged day; every push had a reply line.")

    def test_unset_log_is_nothing(self):
        self.assertEqual(self.line(), "")
        self.assertEqual(self.audited(), [])

    def test_a_week_with_no_row_is_nothing(self):
        self.log([row(NOW - 30 * 24 * H)])
        self.assertEqual(self.line(), "")

    def test_an_unreadable_log_is_nothing(self):
        self.cfg.write_text(json.dumps({"push_log": "absent.jsonl"}))
        self.assertEqual(self.line(), "")

    def test_no_today_is_nothing(self):
        self.log([row(NOW - 3 * H)])
        self.assertEqual(jobs_runner.week_delivery(self.st, self.env, self.root, None, UTC, NOW), "")

    def test_a_digit_is_blocked_by_the_gate(self):
        self.log([row(NOW - 3 * H)])
        with mock.patch.object(delivery_audit, "WITHIN_LOGGED", "within the limit on 2 days"):
            self.assertEqual(self.line(), "")
        self.assertTrue(self.audited()[-1]["blocked"])

    def test_a_broken_audit_does_not_stop_the_review(self):
        self.log([row(NOW - 3 * H)])
        with mock.patch.object(delivery_audit, "audit", side_effect=RuntimeError("boom")):
            self.assertEqual(self.line(), "")


class Review(State):
    def test_the_review_carries_the_line(self):
        self.log([row(NOW - 4 * H, title=jobs.WAKE_BRIEF.send_title,
                      body="Good morning.\nReply: Ok\nWhy now: you woke up")])
        lines = self.review()
        self.assertEqual(lines[1:], [weekly_target.REVIEW_ON_THE_WAY,
                                     "Pushes: within the push limit on every logged day; brief reached you on every "
                                     "wake day; every push had a reply line."])

    def test_week_review_body_carries_it_too(self):
        self.log([row(NOW - 3 * H)])
        text = jobs_runner.week_review_body(self.st, self.habit, None, self.env, self.root, UTC, TODAY, NOW)
        self.assertIn("Pushes: within the push limit", text)

    def test_no_log_leaves_the_review_unchanged(self):
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit), weekly_target.REVIEW_ON_THE_WAY])

    def test_the_log_is_never_written(self):
        p = self.log([row(NOW - 3 * H)])
        before = p.read_text()
        self.review()
        self.assertEqual(p.read_text(), before)


if __name__ == "__main__":
    unittest.main()
