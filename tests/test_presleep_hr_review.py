"""The pre-sleep heart-rate line in the week review (jobs_runner.week_presleep_hr / body / run_once).

Words only, wearable rows only, through tier_audit.gate (hook week_review:presleep_hr); nothing when unknown.
Synthetic rows, a fake push, a fixed clock, UTC as the local zone. No new job and no new push.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
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

from limitless import jobs, jobs_runner, presleep_hr, weekly_target  # noqa: E402
from test_flow_week_hooks import FakePush  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
KD = "\nReply: Keep / Drop"
ABOUT = "Pre-sleep heart rate: about usual most nights (wearable)."


def rows(week=60.0, usual=60.0, modality="measured"):
    """Twenty-one earlier synthetic nights at ``usual`` and the seven nights before TODAY at ``week``."""
    out = [{"night": (TODAY - timedelta(days=b)).isoformat(), "bpm": usual, "modality": modality}
           for b in range(28, 7, -1)]
    return out + [{"night": (TODAY - timedelta(days=b)).isoformat(), "bpm": week, "modality": modality}
                  for b in range(7, 0, -1)]


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

    def presleep(self, data):
        self.cfg.write_text(json.dumps({"presleep_hr_file": "presleep-hr.jsonl"}))
        (self.st / "presleep-hr.jsonl").write_text("".join(json.dumps(r) + "\n" for r in data))

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
    def test_the_line_sits_right_after_the_sleep_line(self):
        text = jobs_runner.body(jobs.WEEK_REVIEW, self.habit, sleep_line="Sleep: s.", naps_line="Naps: n.",
                                presleep_line=ABOUT)
        self.assertEqual(text.split("\n")[-4:-1], ["Sleep: s.", ABOUT, "Naps: n."])

    def test_only_the_week_review_carries_it(self):
        for spec in (jobs.HABIT_CHECKIN, jobs.MIQ):
            self.assertNotIn("Pre-sleep", jobs_runner.body(spec, self.habit, presleep_line=ABOUT))


class Helper(State):
    def test_known_words_from_the_wearable(self):
        self.presleep(rows())
        self.assertEqual(jobs_runner.week_presleep_hr(self.st, self.env, self.root, TODAY), ABOUT)
        self.presleep(rows(week=70.0))
        self.assertEqual(jobs_runner.week_presleep_hr(self.st, self.env, self.root, TODAY),
                         "Pre-sleep heart rate: higher than usual most nights (wearable).")

    def test_unknown_is_nothing(self):
        self.assertEqual(jobs_runner.week_presleep_hr(self.st, self.env, self.root, TODAY), "")   # no file set
        self.presleep(rows())
        self.assertEqual(jobs_runner.week_presleep_hr(self.st, self.env, self.root), "")          # no today
        self.presleep(rows(modality="proxy"))                                                    # phone only
        self.assertEqual(jobs_runner.week_presleep_hr(self.st, self.env, self.root, TODAY), "")
        self.presleep(rows()[:-7])                                                               # no night this week
        self.assertEqual(jobs_runner.week_presleep_hr(self.st, self.env, self.root, TODAY), "")

    def test_the_line_passes_the_tier_audit_gate(self):
        self.presleep(rows())
        jobs_runner.week_presleep_hr(self.st, self.env, self.root, TODAY)
        (row,) = self.audited()
        self.assertEqual((row["hook"], row["tier"], row["blocked"]), ("week_review:presleep_hr", "T1", False))

    def test_a_digit_is_blocked_by_the_gate(self):
        self.presleep(rows())
        with mock.patch.object(presleep_hr, "review_line", return_value="Pre-sleep heart rate: 61 bpm."):
            self.assertEqual(jobs_runner.week_presleep_hr(self.st, self.env, self.root, TODAY), "")
        self.assertTrue(self.audited()[-1]["blocked"])

    def test_a_broken_file_does_not_stop_the_review(self):
        self.presleep([])
        (self.st / "presleep-hr.jsonl").write_bytes(b"\xff\xfe not json\n")
        self.assertEqual(jobs_runner.week_presleep_hr(self.st, self.env, self.root, TODAY), "")


class Review(State):
    def test_the_review_carries_the_words(self):
        self.presleep(rows())
        lines = self.review()
        self.assertEqual(lines[1:], [weekly_target.REVIEW_ON_THE_WAY, ABOUT])
        self.assertEqual(re.findall(r"\d", lines[-1]), [])
        self.assertIn("week_review:presleep_hr", [r["hook"] for r in self.audited()])

    def test_no_file_leaves_the_review_unchanged(self):
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit), weekly_target.REVIEW_ON_THE_WAY])

    def test_no_new_job(self):
        self.assertNotIn("presleep", " ".join(jobs.SPECS).lower())


if __name__ == "__main__":
    unittest.main()
