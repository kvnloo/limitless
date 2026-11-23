"""The idea ledger's line in the week review (jobs_runner.week_ideas / body / run_once).

At most one line, "Ideas recorded this week: <words>.", through tier_audit.gate (hook week_review:ideas);
nothing when no ledger is set. Synthetic rows, a fake push, a fixed clock, UTC. No new job and no new push.
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

from limitless import idea_ledger, jobs, jobs_runner, weekly_target  # noqa: E402
from test_flow_week_hooks import FakePush  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
KD = "\nReply: Keep / Drop"
LINE = "Ideas recorded this week: a few, none triaged."


def idea(text, hours_ago, status="new"):
    return {"kind": "idea", "id": idea_ledger.idea_id(text), "source": "hermes", "status": status, "text": text,
            "at": datetime.fromtimestamp(NOW - hours_ago * 3600, UTC).isoformat()}


class State(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.audit = self.root / "audit.jsonl"
        self.env = {"LIMITLESS_CONFIG": str(self.root / "config.json"), "LIMITLESS_AUDIT": str(self.audit)}
        week_of = TODAY - timedelta(days=6)
        self.habit = {"week_of": week_of.isoformat(), "habit": "Synthetic habit",
                      "checkins": {week_of.isoformat(): "Done"}}
        (self.st / "habit.json").write_text(json.dumps(self.habit))
        (self.st / "events.jsonl").write_text(json.dumps({"event": "habit_cue", "at": NOW - 60}) + "\n")

    def ledger(self, rows):
        p = self.st / "ideas.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.env["LIMITLESS_IDEA_LEDGER"] = str(p)
        return p

    def audited(self):
        return [json.loads(ln) for ln in self.audit.read_text().splitlines()] if self.audit.exists() else []

    def review(self):
        push = FakePush()
        out = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=self.env, home=self.root, tz=UTC)
        self.assertEqual({r["job"]: r for r in out}["Week review"]["action"], jobs.DELIVER, out)
        (text,) = [c[1] for c in push.calls if c[0] == "Week review"]
        self.assertTrue(text.endswith(KD), text)
        return text[:-len(KD)].split("\n")


class Words(unittest.TestCase):
    def test_review_line_words(self):
        cases = {(0, 0): "Ideas recorded this week: none.", (1, 0): "Ideas recorded this week: one, not triaged yet.",
                 (2, 2): "Ideas recorded this week: two, all triaged.", (4, 0): LINE,
                 (7, 3): "Ideas recorded this week: several, some triaged."}
        for (n, t), want in cases.items():
            got = idea_ledger.review_line({"recorded": n, "triaged": t})
            self.assertEqual(got, want)
            self.assertEqual(re.findall(r"\d", got), [])


class Body(State):
    def test_the_line_sits_after_the_anki_line_and_before_the_rule(self):
        text = jobs_runner.body(jobs.WEEK_REVIEW, self.habit, anki_line="Anki: a.", rule_line="Your rule says: r.",
                                ideas_line=LINE)
        self.assertEqual(text.split("\n")[-4:-1], ["Anki: a.", LINE, "Your rule says: r."])

    def test_only_the_week_review_carries_it(self):
        for spec in (jobs.HABIT_CHECKIN, jobs.MIQ, jobs.WAKE_BRIEF):
            self.assertNotIn("Ideas", jobs_runner.body(spec, self.habit, ideas_line=LINE))


class Helper(State):
    def test_words_from_the_ledger(self):
        self.ledger([idea("synthetic a", 200), idea("synthetic b", 30), idea("synthetic c", 20),
                     idea("synthetic d", 2)])
        self.assertEqual(jobs_runner.week_ideas(self.st, NOW, self.env, self.root),
                         "Ideas recorded this week: a few, none triaged.")

    def test_unset_ledger_is_nothing(self):
        self.assertEqual(jobs_runner.week_ideas(self.st, NOW, self.env, self.root), "")
        self.assertEqual(self.audited(), [])

    def test_the_line_passes_the_tier_audit_gate_and_no_text_leaves(self):
        self.ledger([idea("synthetic a", 30)])
        line = jobs_runner.week_ideas(self.st, NOW, self.env, self.root)
        self.assertNotIn("synthetic", line)
        (row,) = self.audited()
        self.assertEqual((row["hook"], row["tier"], row["blocked"]), ("week_review:ideas", "T1", False))

    def test_a_digit_is_blocked_by_the_gate(self):
        self.ledger([idea("synthetic a", 30)])
        with mock.patch.object(idea_ledger, "review_line", return_value="Ideas recorded this week: 3."):
            self.assertEqual(jobs_runner.week_ideas(self.st, NOW, self.env, self.root), "")
        self.assertTrue(self.audited()[-1]["blocked"])

    def test_a_broken_ledger_does_not_stop_the_review(self):
        p = self.ledger([])
        p.write_bytes(b"\xff\xfe not json\n")
        self.assertEqual(jobs_runner.week_ideas(self.st, NOW, self.env, self.root), "Ideas recorded this week: none.")
        with mock.patch.object(idea_ledger, "week", side_effect=RuntimeError("boom")):
            self.assertEqual(jobs_runner.week_ideas(self.st, NOW, self.env, self.root), "")


class Review(State):
    def test_the_review_carries_the_line(self):
        self.ledger([idea("synthetic a", 30), idea("synthetic b", 3, "parked")])
        lines = self.review()
        self.assertEqual(lines[1:], [weekly_target.REVIEW_ON_THE_WAY, "Ideas recorded this week: two, some triaged."])
        self.assertIn("week_review:ideas", [r["hook"] for r in self.audited()])

    def test_no_ledger_leaves_the_review_unchanged(self):
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit), weekly_target.REVIEW_ON_THE_WAY])

    def test_no_new_job(self):
        self.assertNotIn("idea", " ".join(jobs.SPECS).lower())


if __name__ == "__main__":
    unittest.main()
