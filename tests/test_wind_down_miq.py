"""The wind-down line rides inside the one MIQ push: after the question and the overnight line, before
``Reply: Yes / No / Later``, through tier_audit.gate. No new job, no second push, no extra send-gate call.
Quiet (off / tonight / snoozed) and Sleep mode keep the whole push held as before. Synthetic data only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import re
import sys
import tempfile
import unittest
from datetime import timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import jobs, jobs_runner, one_tap, quiet, send_gate, wind_down  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0
MIQ = "MIQ for tonight?"
MIQ_Q = "Your wind-down has started. Do you know the one thing that matters most tomorrow?"
CHOICES = "Reply: Yes / No / Later"
PLAN = "Overnight: a few tasks running, one queued"
LINE = "Screens down and lights low when you're ready."
UTC = timezone.utc


class GatedPush:
    """kevin-push in miniature: every call goes through send_gate.decide (with quiet), and only a "send"
    is a Telegram delivery. ``gate_calls`` counts send-gate calls; ``sent`` is what reached the phone."""

    def __init__(self, state_dir, last_seen=None):
        self.state_dir, self.last_seen = state_dir, last_seen
        self.gate_calls, self.sent, self.log = [], [], []

    def __call__(self, title, body, once=None, why=None):
        evs = jobs_runner.events(jobs_runner.StateReader(Path(self.state_dir)))
        q = quiet.active(quiet.load(self.state_dir), evs, self.last_seen, NOW)
        verdict = send_gate.decide("limitless", title, body, "decision", NOW, self.log, False,
                                   once_key=once, quiet=q)
        self.gate_calls.append((title, verdict))
        if verdict == "drop" and send_gate.quiet_reason(q) is not None:
            return f"log ({send_gate.quiet_reason(q)})"
        if verdict != "send":
            return verdict
        self.log.append({"t": NOW, "k": send_gate.key(title, body), "once": once})
        self.sent.append((title, body))
        return "telegram"


class Body(unittest.TestCase):
    def test_line_after_question_and_overnight_before_choices(self):
        got = jobs_runner.body(jobs.MIQ, overnight=PLAN, wind_down_line=LINE)
        self.assertEqual(got.splitlines(), [MIQ_Q, PLAN, LINE, CHOICES])
        self.assertTrue(one_tap.is_one_tap(got))

    def test_line_without_overnight(self):
        got = jobs_runner.body(jobs.MIQ, wind_down_line=LINE)
        self.assertEqual(got.splitlines(), [MIQ_Q, LINE, CHOICES])
        self.assertTrue(one_tap.is_one_tap(got))

    def test_no_line_keeps_the_body(self):
        self.assertEqual(jobs_runner.body(jobs.MIQ, overnight=PLAN), f"{MIQ_Q}\n{PLAN}\n{CHOICES}")
        self.assertEqual(jobs_runner.body(jobs.MIQ, wind_down_line=""), f"{MIQ_Q}\n{CHOICES}")

    def test_other_jobs_never_get_the_line(self):
        for spec in jobs.SPECS.values():
            if spec.name != jobs.MIQ.name:
                self.assertNotIn(LINE, jobs_runner.body(spec, wind_down_line=LINE), spec.name)

    def test_no_new_job(self):
        self.assertEqual(sorted(jobs.SPECS), ["break_nudge", "habit_checkin", "miq", "nap", "wake_brief",
                                              "week_review"])
        self.assertNotIn("wind_down_line", " ".join(s.name for s in jobs.SPECS.values()))


class WindDownRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.cfg.write_text("{}")
        self.att = self.root / "attention.json"
        self.audit = self.root / "audit.jsonl"
        self.glide(nudged="")
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_GLIDE_ATTENTION": str(self.att),
                    "LIMITLESS_AUDIT": str(self.audit)}
        self.sleepmode([{"at": NOW - 14 * H, "on": True}, {"at": NOW - 6 * H, "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
        (self.st / "unlocks.jsonl").write_text(json.dumps({"at": NOW - 120}) + "\n")
        (self.st / "events.jsonl").write_text(json.dumps({"event": "wind_down", "at": NOW - 60}) + "\n")

    def glide(self, nudged):
        self.att.write_text(json.dumps({"block": None, "queue": [], "resume": {"saved": NOW - 120},
                                        "nudged": nudged}))

    def sleepmode(self, rows):
        (self.st / "sleepmode.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def tonight(self):
        evs = jobs_runner.events(jobs_runner.StateReader(self.st), env=self.env, home=self.root)
        return jobs_runner.night_date(evs, NOW - 60, UTC)

    def run_(self, push=None):
        push = push or GatedPush(self.st)
        rows = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=self.env, home=self.root, tz=UTC)
        return {r["job"]: r for r in rows}, push

    def miq_calls(self, push):
        return [c for c in push.gate_calls if c[0] == MIQ]

    def test_exactly_one_push_at_wind_down_with_the_line(self):
        rows, push = self.run_()
        self.assertEqual(rows[MIQ]["action"], jobs.DELIVER, rows)
        self.assertEqual(self.miq_calls(push), [(MIQ, "send")])             # one send-gate call, one send
        body = dict(push.sent)[MIQ]
        self.assertEqual(body.splitlines(), [MIQ_Q, LINE, CHOICES])
        self.assertTrue(one_tap.is_one_tap(body))
        self.assertEqual(re.findall(r"\d", body), [])
        titles = {s.send_title for s in jobs.SPECS.values()}
        self.assertTrue({t for t, _ in push.gate_calls} <= titles)          # no new title, no new push

    def test_a_second_run_sends_nothing_more(self):
        _, push = self.run_()
        rows, push2 = self.run_(push)
        self.assertEqual(self.miq_calls(push2), [(MIQ, "send")])            # still the first one only
        self.assertEqual(len([t for t, _ in push2.sent if t == MIQ]), 1)
        self.assertNotEqual(rows[MIQ]["action"], jobs.DELIVER)

    def test_same_gate_calls_with_and_without_the_line(self):
        _, with_line = self.run_()
        self.cfg.write_text(json.dumps({"wind_down_line": "off"}))
        (self.st / jobs_runner.SENT_LOG).unlink()
        _, without = self.run_()
        self.assertEqual(with_line.gate_calls, without.gate_calls)          # no extra send-gate slot

    def test_off_means_no_line(self):
        self.cfg.write_text(json.dumps({"wind_down_line": "off"}))
        _, push = self.run_()
        self.assertEqual(dict(push.sent)[MIQ], f"{MIQ_Q}\n{CHOICES}")

    def test_configured_line(self):
        self.cfg.write_text(json.dumps({"wind_down_line": "Lights low when you're ready."}))
        _, push = self.run_()
        self.assertEqual(dict(push.sent)[MIQ].splitlines(), [MIQ_Q, "Lights low when you're ready.", CHOICES])

    def test_glide_already_nudged_tonight_means_no_line(self):
        self.glide(nudged=self.tonight())
        rows, push = self.run_()
        self.assertEqual(self.miq_calls(push), [(MIQ, "send")])             # the question still goes, once
        self.assertEqual(dict(push.sent)[MIQ], f"{MIQ_Q}\n{CHOICES}")

    def test_glide_nudge_from_another_night_keeps_the_line(self):
        self.glide(nudged="2001-01-01")
        _, push = self.run_()
        self.assertIn(LINE, dict(push.sent)[MIQ].splitlines())

    def test_line_after_the_overnight_line(self):
        self.cfg.write_text(json.dumps({"work_queue_dir": "lanes"}))
        for sub, n in (("running", "synthetic-alpha"), ("running", "synthetic-beta"), ("queue", "synthetic-gamma")):
            p = self.st / "lanes" / sub / f"{n}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("synthetic\n")
        _, push = self.run_()
        self.assertEqual(dict(push.sent)[MIQ].splitlines(), [MIQ_Q, PLAN, LINE, CHOICES])

    def test_line_goes_through_tier_audit(self):
        self.run_()
        rows = [json.loads(x) for x in self.audit.read_text().splitlines()]
        mine = [r for r in rows if r["hook"] == "miq:wind_down"]
        self.assertEqual(len(mine), 1, rows)
        self.assertEqual((mine[0]["tier"], mine[0]["blocked"], mine[0]["lines"]), ("T1", False, 1))
        self.assertNotIn("Screens", self.audit.read_text())                 # content-free

    def test_a_digit_in_the_line_is_blocked_not_sent(self):
        with mock.patch.object(wind_down, "line", return_value="Screens down by 9."):
            _, push = self.run_()
        self.assertEqual(dict(push.sent)[MIQ], f"{MIQ_Q}\n{CHOICES}")
        rows = [json.loads(x) for x in self.audit.read_text().splitlines()]
        self.assertTrue(any(r["hook"] == "miq:wind_down" and r["blocked"] for r in rows), rows)

    def test_a_broken_line_never_stops_the_question(self):
        with mock.patch.object(wind_down, "line", side_effect=RuntimeError("synthetic")):
            _, push = self.run_()
        self.assertEqual(dict(push.sent)[MIQ], f"{MIQ_Q}\n{CHOICES}")

    def test_quiet_holds_the_whole_push(self):
        for mode in ("off", "quiet_tonight", "snoozed"):
            with self.subTest(mode=mode):
                (self.st / jobs_runner.SENT_LOG).unlink(missing_ok=True)
                quiet.write(self.st, mode, NOW - 2 * H)
                rows, push = self.run_()
                self.assertEqual(self.miq_calls(push), [(MIQ, "drop")])     # the one gate call, dropped
                self.assertEqual(push.sent, [])
                self.assertEqual(rows[MIQ]["action"], jobs.DROP, rows)
                self.assertFalse((self.st / jobs_runner.SENT_LOG).exists())

    def test_sleep_mode_on_holds_the_whole_push(self):
        self.sleepmode([{"at": NOW - 14 * H, "on": True}, {"at": NOW - 6 * H, "on": False},
                        {"at": NOW - 30, "on": True}])
        rows, push = self.run_()
        self.assertEqual(self.miq_calls(push), [])
        self.assertEqual(push.sent, [])
        self.assertNotEqual(rows[MIQ]["action"], jobs.DELIVER, rows)

    def test_dry_run_never_pushes(self):
        push = GatedPush(self.st)
        jobs_runner.run_once(self.st, NOW, push=push, dry_run=True, env=self.env, home=self.root, tz=UTC)
        self.assertEqual(push.gate_calls, [])


if __name__ == "__main__":
    unittest.main()
