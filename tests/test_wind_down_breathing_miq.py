"""The breathing choice rides in the one MIQ push, inside the wind-down line: no new push, no new job, no
extra send-gate call, still one line through tier_audit.gate (hook miq:wind_down). Synthetic data only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from limitless import jobs, jobs_runner, one_tap, wind_down  # noqa: E402
import test_wind_down_miq as base  # noqa: E402

LINK = "example://breathe"
MIQ, MIQ_Q, CHOICES = base.MIQ, base.MIQ_Q, base.CHOICES
WITH_LINK = ("Screens down and lights low when you're ready, or slow breathing in your app (without heart data): "
             + LINK)


class BreathingRun(unittest.TestCase):
    setUp = base.WindDownRun.setUp
    glide = base.WindDownRun.glide
    sleepmode = base.WindDownRun.sleepmode
    tonight = base.WindDownRun.tonight
    run_ = base.WindDownRun.run_
    miq_calls = base.WindDownRun.miq_calls

    def configure(self, **extra):
        self.cfg.write_text(json.dumps({wind_down.BREATHING_KEY: LINK, **extra}))

    def test_one_push_with_the_breathing_choice_in_the_line(self):
        self.configure()
        rows, push = self.run_()
        self.assertEqual(rows[MIQ]["action"], jobs.DELIVER, rows)
        self.assertEqual(self.miq_calls(push), [(MIQ, "send")])
        body = dict(push.sent)[MIQ]
        self.assertEqual(body.splitlines(), [MIQ_Q, WITH_LINK, CHOICES])
        self.assertTrue(one_tap.is_one_tap(body))
        self.assertEqual(re.findall(r"\d", body), [])
        self.assertEqual([t for t, _ in push.sent], [MIQ])                # nothing else went out

    def test_same_gate_calls_with_and_without_the_link(self):
        _, without = self.run_()
        (self.st / jobs_runner.SENT_LOG).unlink()
        self.configure()
        _, with_link = self.run_()
        self.assertEqual(with_link.gate_calls, without.gate_calls)       # no extra send-gate slot
        self.assertEqual(sorted(jobs.SPECS), ["break_nudge", "habit_checkin", "miq", "nap", "wake_brief",
                                              "week_review"])                # no new job

    def test_still_one_audited_line(self):
        self.configure()
        self.run_()
        rows = [json.loads(x) for x in self.audit.read_text().splitlines()]
        mine = [r for r in rows if r["hook"] == "miq:wind_down"]
        self.assertEqual(len(mine), 1, rows)
        self.assertEqual((mine[0]["tier"], mine[0]["blocked"], mine[0]["lines"]), ("T1", False, 1))
        self.assertNotIn("breathe", self.audit.read_text())               # content-free

    def test_line_off_keeps_the_choice_alone(self):
        self.configure(wind_down_line="off")
        _, push = self.run_()
        self.assertEqual(dict(push.sent)[MIQ].splitlines(),
                         [MIQ_Q, "Slow breathing in your app when you're ready (without heart data): " + LINK, CHOICES])

    def test_glide_nudged_tonight_means_no_line_at_all(self):
        self.configure()
        self.glide(nudged=self.tonight())
        _, push = self.run_()
        self.assertEqual(dict(push.sent)[MIQ], f"{MIQ_Q}\n{CHOICES}")

    def test_a_link_with_a_digit_is_never_sent(self):
        self.cfg.write_text(json.dumps({wind_down.BREATHING_KEY: "example://breathe4"}))
        _, push = self.run_()
        self.assertEqual(dict(push.sent)[MIQ].splitlines(), [MIQ_Q, base.LINE, CHOICES])


if __name__ == "__main__":
    unittest.main()
