"""Contract: every job's message, built from synthetic fixtures with every optional line present, is delivered
by bin/kevin-push within the message_shape limits, TLDR first, still ending with its Reply line (then the one
Why-now line). Fake `hermes` on PATH, temp HOME; synthetic data only, no real person's numbers."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "kevin-push"
FIX = ROOT / "tests" / "fixtures" / "state"
sys.path.insert(0, str(ROOT))
from limitless import (anki, body as body_, brief_post, flow_metrics, flow_week, idea_ledger, jobs,  # noqa: E402
                       jobs_runner, message_shape, naps, one_tap, overnight, passive_habit, presleep_hr, rides,
                       send_gate, sleep, stop_rule, weekly_target, wind_down)
from limitless.state_reader import StateReader  # noqa: E402

NOW = 1894708800.0
LIM = message_shape.limits({})
HABIT = json.loads((FIX / "habit.json").read_text())
SYNCED = StateReader(FIX).habit_days()
QUEUE = [{"status": "running"}, {"status": "queued"}, {"status": "queued"},
         {"status": "done", "mtime": NOW - 60}, {"status": "failed", "mtime": NOW - 30}]


def week_review_body():
    """The week review with every optional line, each from its own module's words."""
    lab = lambda w: {"label": {"label": w}}   # noqa: E731
    return jobs_runner.body(
        jobs.week_review(HABIT), HABIT, None, SYNCED,
        flow=flow_week.review_line(None),
        passive=passive_habit.review_line({"days_measured": 7, "days_met": 6}),
        body_line=body_.review_line(lab(body_.LABELS[1])),
        fragment=flow_metrics.review_line(flow_metrics.LABELS[1]),
        rides_line=rides.review_line(lab(rides.LABELS[2])),
        sleep_line=sleep.review_line({"label": sleep.LABELS[1]}),
        presleep_line=presleep_hr.review_line({"word": presleep_hr.WORDS[0]}),
        naps_line=naps.week_line({"naps": [{}, {}], "close": 1}) + ".",
        anki_line=anki.review_line(lab(anki.SOME)),
        ideas_line=idea_ledger.review_line({"recorded": 3, "triaged": 0}),
        experiment_line=jobs_runner.EXPERIMENT_PENDING_LINE,
        rule_line=stop_rule.review_line(stop_rule.KEEP) or "Your rule says: keep it",
        target_days=weekly_target.DEFAULT_TARGET_DAYS)


def miq_body():
    cfg = {"wind_down_breathing_link": "https://example.org/breathe"}
    return jobs_runner.body(jobs.MIQ, overnight=overnight.plan_line(QUEUE),
                            wind_down_line=wind_down.line(cfg, None, None, heart_live=True))


def checkin_body():
    habit = dict(HABIT, checkins={d: "Done" for d in ("2030-01-11", "2030-01-12", "2030-01-13", "2030-01-14",
                                                      "2030-01-15")})
    return jobs_runner.body(jobs.habit_checkin(habit), habit, {"seen": True, "count": 1}, None,
                            target_days=weekly_target.DEFAULT_TARGET_DAYS)


def wake_brief_body():
    notif = ("Good morning: today has one long focus window before lunch.\n"
             "Sleep: about usual by the phone proxy.\n"
             "Top thing: finish the draft you started yesterday.")
    asks = {"at": NOW - 60, "lines": ["A1: review the plan t_0123abcd (two days)", "A2: pick a slot"]}
    return brief_post.finalize(notif, asks, NOW, saved=2, overnight=overnight.landed_line(QUEUE),
                               naps="Naps yesterday: one short nap (phone Sleep mode)",
                               work=jobs_runner.BRIEF_WORK.format("two long blocks, one with a feed leak; three items landed"))


def nap_body():
    return jobs_runner.body(jobs.NAP)


# (title, body builder, asks): the title kevin-push sends it under, as its sender does
JOBS = {
    "wake brief": ("Wake-up brief", wake_brief_body, False),
    "MIQ": ("MIQ for tonight?", miq_body, True),
    "week review": (jobs.WEEK_REVIEW.send_title, week_review_body, True),
    "habit check-in": (jobs.HABIT_CHECKIN.send_title, checkin_body, True),
    "nap": ("Back from nap", nap_body, False),
}


class Contract(unittest.TestCase):
    def deliver(self, title, text):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            fakebin = home / "fakebin"
            fakebin.mkdir()
            hermes = fakebin / "hermes"
            hermes.write_text("#!/bin/sh\nwhile [ $# -gt 0 ]; do [ \"$1\" = --file ] && cp \"$2\" \"$HOME/sent.txt\"; shift; done\n")
            hermes.chmod(hermes.stat().st_mode | stat.S_IEXEC)
            env = dict(os.environ, HOME=str(home), PATH=f"{fakebin}:{os.environ['PATH']}",
                       LIMITLESS_SLEEPMODE=str(home / "none.jsonl"), LIMITLESS_STATE=str(home / "state"),
                       LIMITLESS_CONFIG=str(home / "config.json"), CIRCADIAN_CLASS="decision")
            r = subprocess.run([sys.executable, "-I", str(CLI), "limitless", title, text], env=child_env(env),
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("telegram", r.stdout)
            return (home / "sent.txt").read_text()

    def test_every_job_is_delivered_within_the_limits(self):
        for name, (title, build, asking) in JOBS.items():
            with self.subTest(job=name):
                before = build()
                out = self.deliver(title, before)
                lines = [ln for ln in out.splitlines() if ln.strip()]
                self.assertLessEqual(len(lines), LIM["max_lines"], out)
                for ln in lines:
                    self.assertTrue(len(ln) <= LIM["max_line_chars"] or "://" in ln, ln)
                self.assertEqual(lines[0], before.splitlines()[0])            # the TLDR, as it was
                self.assertTrue(lines[-1].startswith(send_gate.WHY_PREFIX))   # the one Why-now line, last
                self.assertLessEqual(sum(c.isdigit() for c in out), sum(c.isdigit() for c in before))
                if asking:
                    self.assertEqual(lines[-2], before.splitlines()[-1])     # still ends with its Reply line
                    self.assertIsNotNone(one_tap.choices_of(lines[-2]))
                    self.assertTrue(one_tap.is_one_tap(out))

    def test_the_fixtures_have_every_optional_line(self):
        self.assertGreaterEqual(len(week_review_body().splitlines()), 15)
        self.assertEqual(len(miq_body().splitlines()), 4)
        self.assertIn("://", miq_body())
        self.assertEqual(len(checkin_body().splitlines()), 4)
        self.assertEqual(len(wake_brief_body().splitlines()), 8)

    def test_the_long_messages_were_folded(self):
        for name in ("week review", "wake brief"):
            title, build, _ = JOBS[name]
            self.assertIn(" more lines in the plugin", self.deliver(title, build()), name)


if __name__ == "__main__":
    unittest.main()
