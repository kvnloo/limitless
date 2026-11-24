"""The sender_confirm event job (limitless/sender_confirm_job.py): config off / dry_run / write, the event is the
owner's reply setting the sender (push-sender.json's ``at``, never a clock), one plain confirmation per change
through push with --once sender_confirm:<at>, the mark sender-confirm.json words and epochs only. Synthetic state
in a temp dir, a fixed clock, env passed explicitly; push is a fake callable, never kevin-push.""" 
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, jobs_runner, push_sender, send_gate  # noqa: E402
from limitless import sender_confirm_job as job  # noqa: E402

NOW = 1894708800.0   # 2030-01-15T12:00:00Z
H = 3600
PROFILE = "backup-bot"        # a synthetic profile name; it must never reach a message, a reason or the mark
AT = NOW - 120
KEY = f"sender_confirm:{int(AT)}"


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
        self.reply(AT)

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, mode):
        self.cfg_path.write_text(json.dumps({"sender_confirm": mode} if mode else {}))

    def reply(self, at, name=PROFILE):
        (self.st / push_sender.REPLY_FILE).write_text(json.dumps({"profile": name, "at": at}))

    def run_job(self, push=None, dry_run=False, now=NOW, env=None):
        return job.run(self.st, now, push=push, dry_run=dry_run, env=self.env if env is None else env)

    def mark(self):
        p = self.st / job.MARK
        return json.loads(p.read_text()) if p.exists() else None

    def clean(self, *texts):
        for t in texts:
            self.assertIsNone(re.search(r"\d", t), t)
            self.assertNotIn(PROFILE, t)
            self.assertNotIn("/", t)

    def test_off_by_default_no_row_and_nothing_read(self):
        push = FakePush()
        self.config(None)
        self.assertIsNone(self.run_job(push))
        self.config("off")
        self.assertIsNone(self.run_job(push))
        self.config("loud")
        self.assertIsNone(self.run_job(push))
        self.assertEqual(push.calls, [])
        self.assertIsNone(self.mark())

    def test_write_sends_one_plain_confirmation_with_its_once_key_and_marks_it_told(self):
        push = FakePush()
        r = self.run_job(push)
        self.assertEqual((r["job"], r["action"]), (job.TITLE, jobs.DELIVER), r)
        self.assertTrue(r["reason"].endswith("sent"), r)
        self.assertEqual(len(push.calls), 1)
        call = push.calls[0]
        self.assertEqual((call["title"], call["body"], call["once"], call["why"]),
                         ("Pushes", job.BODY, KEY, job.WHY))
        self.assertEqual(job.BODY, "This is the new route for your phone pushes. If you see this, it works.")
        self.clean(call["title"], call["body"], call["why"], r["reason"])
        self.assertNotIn("t_", call["body"])
        m = self.mark()
        self.assertEqual((m["reply_at"], m["outcome"]), (AT, job.TOLD))
        self.assertEqual(stat.S_IMODE((self.st / job.MARK).stat().st_mode), 0o600)
        text = (self.st / job.MARK).read_text()
        for word in (PROFILE, "route", "Pushes", "phone"):          # no name and no message text in the mark
            self.assertNotIn(word, text)

    def test_a_replay_never_sends_twice_and_a_new_reply_sends_again(self):
        push = FakePush()
        self.run_job(push)
        r = self.run_job(push, now=NOW + 300)
        self.assertEqual(r["action"], jobs.DROP)
        self.assertIn("already confirmed", r["reason"])
        self.assertEqual(len(push.calls), 1)
        self.reply(NOW + 600, "other-bot")
        r = self.run_job(push, now=NOW + 900)
        self.assertEqual(r["action"], jobs.DELIVER)
        self.assertEqual([c["once"] for c in push.calls], [KEY, f"sender_confirm:{int(NOW + 600)}"])

    def test_dry_run_writes_nothing_but_says_what_it_would_send(self):
        push = FakePush()
        self.config("dry_run")
        r = self.run_job(push)
        self.assertEqual(r["action"], jobs.DELIVER)
        self.assertIn("would send", r["reason"])
        self.assertIn(job.BODY, r["reason"])
        self.assertIn('config sender_confirm "write" sends it', r["reason"])
        self.config("write")
        self.assertIn("dry run of limitless-jobs", self.run_job(push, dry_run=True)["reason"])
        self.assertIn("would send", self.run_job(None)["reason"])
        self.assertEqual(push.calls, [])
        self.assertIsNone(self.mark())

    def test_a_failed_send_says_the_new_sender_did_not_reach_you_and_the_next_pass_tries_again(self):
        for how, said in (("log (telegram rc=1) (exit 3)", "the send failed"),
                          ("log (no sender profile) (exit 3)", "the sender profile does not exist"),
                          ("kevin-push did not run (FileNotFoundError)", "the send failed")):
            (self.st / job.MARK).unlink(missing_ok=True)
            r = self.run_job(FakePush(how))
            self.assertEqual(r["action"], jobs.HOLD, how)
            self.assertIn("the new sender did not reach you", r["reason"])
            self.assertIn(said, r["reason"])
            self.clean(r["reason"])
            self.assertEqual(self.mark()["outcome"], job.FAILED)
        good = FakePush()
        self.assertEqual(self.run_job(good, now=NOW + 300)["action"], jobs.DELIVER)
        self.assertEqual(good.calls[0]["once"], KEY)
        self.assertEqual(self.mark()["outcome"], job.TOLD)

    def test_a_sleep_mode_hold_waits_and_the_next_pass_tries_again(self):
        r = self.run_job(FakePush("held (sleep mode) (exit 3)"))
        self.assertEqual(r["action"], jobs.HOLD)
        self.assertIn("Sleep mode holds it", r["reason"])
        self.clean(r["reason"])
        self.assertEqual(self.mark()["outcome"], job.HELD)
        again = FakePush()
        self.assertEqual(self.run_job(again, now=NOW + 300)["action"], jobs.DELIVER)
        self.assertEqual(len(again.calls), 1)

    def test_a_quiet_once_or_repeat_drop_settles_it_without_telling(self):
        for how in (f"log ({send_gate.ONCE_DROP}) (exit 3)", "log (quiet: snoozed) (exit 3)",
                    "log (duplicate) (exit 3)"):
            (self.st / job.MARK).unlink(missing_ok=True)
            r = self.run_job(FakePush(how))
            self.assertEqual(r["action"], jobs.DROP, how)
            self.assertEqual(self.mark()["outcome"], job.DROPPED)
            again = FakePush()
            self.assertEqual(self.run_job(again, now=NOW + 300)["action"], jobs.DROP)
            self.assertEqual(again.calls, [])

    def test_the_daily_cap_holds_without_a_mark(self):
        r = self.run_job(FakePush("log (daily cap) (exit 3)"))
        self.assertEqual(r["action"], jobs.HOLD)
        self.assertIn("daily cap", r["reason"])
        self.clean(r["reason"])
        self.assertIsNone(self.mark())

    def test_no_reply_a_late_one_or_an_env_sender_sends_nothing(self):
        push = FakePush()
        r = self.run_job(push, now=AT + jobs.SENDER_CONFIRM_STALE_S + 60)
        self.assertEqual(r["action"], jobs.DROP)
        self.assertIn("too late", r["reason"])
        r = self.run_job(push, env=dict(self.env, KEVIN_PUSH_PROFILE="pinned"))
        self.assertEqual(r["action"], jobs.NOT_TRIGGERED)
        self.assertIn("KEVIN_PUSH_PROFILE is set and still wins", r["reason"])
        self.assertNotIn("pinned", r["reason"])
        (self.st / push_sender.REPLY_FILE).unlink()
        r = self.run_job(push)
        self.assertEqual((r["action"], r["reason"]), (jobs.NOT_TRIGGERED, jobs.SENDER_NO_REPLY))
        self.assertEqual(push.calls, [])
        self.assertIsNone(self.mark())

    def test_a_push_that_raises_is_a_failed_send_never_a_traceback(self):
        def boom(title, body, once=None, why=None):
            raise RuntimeError("x")
        r = self.run_job(boom)
        self.assertEqual(r["action"], jobs.HOLD)
        self.assertIn("did not reach you", r["reason"])

    def test_run_once_carries_the_row_right_after_the_sender_ingest_and_sends_through_its_push(self):
        push = FakePush()
        rows = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=self.env)
        mine = [r for r in rows if r["job"] == job.TITLE]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["action"], jobs.DELIVER)
        self.assertEqual([c["once"] for c in push.calls if c["title"] == "Pushes"], [KEY])
        self.config("off")
        rows = jobs_runner.run_once(self.st, NOW, push=None, dry_run=True, env=self.env)
        self.assertEqual([r for r in rows if r["job"] == job.TITLE], [])


if __name__ == "__main__":
    unittest.main()
