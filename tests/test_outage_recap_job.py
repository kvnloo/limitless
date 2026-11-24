"""The outage_recap event job (limitless/outage_recap_job.py): config off / dry_run / write, the event is a push
delivered after an outage (never a clock), one recap per outage through push with --once, the mark written only on
a real delivery. Synthetic kevin-push logs in a temp state dir, a fixed clock, UTC, env passed explicitly; push is
a fake callable, never kevin-push."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import stat
import sys
import tempfile
import unittest
from datetime import timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, jobs_runner, outage_recap, send_gate  # noqa: E402
from limitless import outage_recap_job as job  # noqa: E402

UTC = timezone.utc
NOW = 1894708800.0   # 2030-01-15T12:00:00Z
H, D = 3600, 86400
RC1, NO_SENDER = "log (telegram rc=1)", "log (no sender profile)"
WAKE, MIQ, NAP = jobs.WAKE_BRIEF.send_title, jobs.MIQ.send_title, jobs.NAP.send_title


def row(at, title, how):
    return {"at": int(at), "tag": "limitless", "cls": "decision", "title": title, "how": how,
            "body": "Private body words.\nReply: Yes / No\nWhy now: a reason"}


START = NOW - D - 2 * H
OPEN = [row(START - H, "Week review", "telegram"), row(START, WAKE, RC1), row(START + 2 * H, MIQ, NO_SENDER),
        row(START + 4 * H, NAP, RC1)]
CLOSED = OPEN + [row(NOW - 600, "Habit check-in", "telegram")]
KEY = f"outage_recap:{int(START)}"


class FakePush:
    def __init__(self, how="telegram"):
        self.how, self.calls = how, []

    def __call__(self, title, body, once=None, why=None):
        self.calls.append({"title": title, "body": body, "once": once, "why": why})
        return self.how


class Job(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg_path = self.root / "config.json"
        self.env = {"HOME": str(self.root), "LIMITLESS_CONFIG": str(self.cfg_path)}
        self.config("write")

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, mode, log="push-log.jsonl"):
        cfg = {"outage_recap": mode}
        if log:
            cfg["push_log"] = log
        self.cfg_path.write_text(json.dumps(cfg))

    def log(self, rows):
        (self.st / "push-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def run_job(self, push=None, dry_run=False, now=NOW):
        return job.run(self.st, now, push=push, dry_run=dry_run, env=self.env, tz=UTC)

    def mark(self):
        p = self.st / job.MARK
        return json.loads(p.read_text()) if p.exists() else None

    def test_off_by_default_no_row_and_nothing_read(self):
        self.cfg_path.write_text(json.dumps({"push_log": "push-log.jsonl"}))
        self.log(CLOSED)
        push = FakePush()
        self.assertIsNone(self.run_job(push))
        self.config("off")
        self.assertIsNone(self.run_job(push))
        self.config("loud")                       # anything else is off
        self.assertIsNone(self.run_job(push))
        self.assertEqual(push.calls, [])
        self.assertEqual(job.mode({}), job.OFF)

    def test_write_sends_one_recap_with_its_once_key_and_marks_it_told(self):
        self.log(CLOSED)
        push = FakePush()
        r = self.run_job(push)
        self.assertEqual((r["job"], r["action"]), (job.TITLE, jobs.DELIVER), r)
        self.assertTrue(r["reason"].endswith("sent"), r)
        self.assertEqual(len(push.calls), 1)
        call = push.calls[0]
        self.assertEqual((call["title"], call["once"]), (outage_recap.TITLE, KEY))
        self.assertEqual(call["body"], outage_recap.recap(CLOSED, NOW, UTC)["body"])
        self.assertEqual(call["why"], job.WHY)
        self.assertIsNone(re.search(r"\d", call["why"] + r["reason"]))
        m = self.mark()
        self.assertEqual((m["key"], m["outcome"]), (KEY, job.TOLD))
        self.assertEqual(stat.S_IMODE((self.st / job.MARK).stat().st_mode), 0o600)
        text = (self.st / job.MARK).read_text()
        for word in ("Private", "wake", "Week", "Pushes"):        # no message text or kinds in the mark
            self.assertNotIn(word, text)

    def test_a_repeat_poll_does_not_send_again(self):
        self.log(CLOSED)
        push = FakePush()
        self.run_job(push)
        r = self.run_job(push, now=NOW + 300)
        self.assertEqual(r["action"], jobs.DROP)
        self.assertIn("already told", r["reason"])
        self.assertEqual(len(push.calls), 1)

    def test_an_outage_still_open_sends_nothing(self):
        self.log(OPEN)
        push = FakePush()
        r = self.run_job(push)
        self.assertEqual(r["action"], jobs.NOT_TRIGGERED)
        self.assertIn("still failing", r["reason"])
        self.assertEqual(push.calls, [])
        self.assertIsNone(self.mark())

    def test_two_outages_only_the_last_is_told(self):
        first = [row(NOW - 4 * D, WAKE, RC1), row(NOW - 4 * D + H, MIQ, RC1), row(NOW - 4 * D + 2 * H, NAP, "telegram")]
        self.log(first + CLOSED)
        push = FakePush()
        self.run_job(push)
        self.assertEqual([c["once"] for c in push.calls], [KEY])

    def test_no_outage_or_no_push_log_is_nothing(self):
        self.log([row(NOW - H, WAKE, "telegram")])
        r = self.run_job(FakePush())
        self.assertEqual(r["action"], jobs.NOT_TRIGGERED)
        self.assertEqual(r["reason"], job.NOTHING_REASON)
        self.config("write", log=None)
        self.assertEqual(self.run_job(FakePush())["reason"], job.NO_LOG_REASON)
        self.config("write", log="missing.jsonl")
        self.assertEqual(self.run_job(FakePush())["reason"], job.UNREADABLE_REASON)

    def test_dry_run_config_or_a_dry_pass_never_pushes_or_writes(self):
        self.log(CLOSED)
        push = FakePush()
        self.config("dry_run")
        r = self.run_job(push)
        self.assertEqual(r["action"], jobs.DELIVER)
        self.assertIn("would send", r["reason"])
        self.config("write")
        r = self.run_job(push, dry_run=True)
        self.assertIn("dry run", r["reason"])
        self.assertIn("would send", self.run_job(None)["reason"])
        self.assertEqual(push.calls, [])
        self.assertIsNone(self.mark())

    def test_a_failed_delivery_holds_without_a_mark_and_the_next_poll_tries_again(self):
        self.log(CLOSED)
        bad = FakePush("log (telegram rc=1) (exit 3)")
        r = self.run_job(bad)
        self.assertEqual(r["action"], jobs.HOLD)
        self.assertIsNone(self.mark())
        good = FakePush()
        self.assertEqual(self.run_job(good, now=NOW + 300)["action"], jobs.DELIVER)
        self.assertEqual(good.calls[0]["once"], KEY)

    def test_a_once_drop_or_quiet_drop_settles_it_without_marking_it_told(self):
        for how in (f"log ({send_gate.ONCE_DROP}) (exit 3)", "log (quiet: snoozed) (exit 3)"):
            (self.st / job.MARK).unlink(missing_ok=True)
            self.log(CLOSED)
            r = self.run_job(FakePush(how))
            self.assertEqual(r["action"], jobs.DROP, how)
            self.assertEqual(self.mark()["outcome"], job.DROPPED)
            again = FakePush()
            self.assertEqual(self.run_job(again, now=NOW + 300)["action"], jobs.DROP)
            self.assertEqual(again.calls, [])

    def test_a_late_recap_is_noise(self):
        self.log(CLOSED)
        push = FakePush()
        r = self.run_job(push, now=NOW - 600 + job.STALE_S + 60)
        self.assertEqual(r["action"], jobs.DROP)
        self.assertIn("too late", r["reason"])
        self.assertEqual(push.calls, [])

    def test_the_spec_is_an_event_never_a_clock(self):
        spec = jobs.OUTAGE_RECAP
        self.assertEqual(spec.trigger_event, "push_back")
        self.assertIn("push_back", jobs.EVENTS)
        self.assertNotIn(spec.name, jobs.SPECS)          # not a should_fire job: no window, its own event
        self.assertEqual(spec.stale_after_s, job.STALE_S)

    def test_run_once_carries_the_row_and_sends_through_its_push(self):
        self.log(CLOSED)
        push = FakePush()
        rows = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=self.env, tz=UTC)
        mine = [r for r in rows if r["job"] == job.TITLE]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["action"], jobs.DELIVER)
        self.assertEqual([c["once"] for c in push.calls if c["title"] == outage_recap.TITLE], [KEY])
        self.config("off")
        rows = jobs_runner.run_once(self.st, NOW, push=None, dry_run=True, env=self.env, tz=UTC)
        self.assertEqual([r for r in rows if r["job"] == job.TITLE], [])


if __name__ == "__main__":
    unittest.main()
