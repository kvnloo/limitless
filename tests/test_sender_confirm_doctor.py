"""The sender confirmation's doctor row (doctor.sender_confirm_row, sender_confirm_job.state): the confirmation's
own delivery result in kevin-push's log (config push_log) is the proof; the mark sender-confirm.json is the
fallback. Synthetic logs and marks in a temp state dir, a fixed clock, env passed explicitly. Nothing is sent.""" 
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import doctor, jobs, push_sender  # noqa: E402
from limitless import sender_confirm_job as job  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 1894708800.0   # 2030-01-15T12:00:00Z
H = 3600
AT = NOW - 2 * H
PROFILE = "backup-bot"


def log_row(at, how, title="Pushes", body=job.BODY + "\nWhy now: " + job.WHY):
    return {"at": int(at), "tag": "limitless", "cls": "decision", "title": title, "body": body, "how": how}


class DoctorRow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)
        self.reader = StateReader(self.st)
        (self.st / push_sender.REPLY_FILE).write_text(json.dumps({"profile": PROFILE, "at": AT}))

    def tearDown(self):
        self.tmp.cleanup()

    def log(self, rows):
        (self.st / "push-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def mark(self, outcome, reply_at=AT):
        (self.st / job.MARK).write_text(json.dumps({"reply_at": reply_at, "outcome": outcome, "ran_at": NOW - H}))

    def row(self, mode="write", log="push-log.jsonl", now=NOW, env=None):
        cfg = {"sender_confirm": mode} if mode else {}
        if log:
            cfg["push_log"] = log
        r = doctor.sender_confirm_row(self.reader, cfg, now, env={} if env is None else env)
        self.assertEqual((r["name"], r["kind"]), (doctor.SENDER_CONFIRM_ROW, "job"))
        self.assertIsNone(re.search(r"\d", doctor.words(r["reason"])), r["reason"])
        self.assertNotIn(PROFILE, r["reason"])
        return r

    def test_off(self):
        r = self.row(mode=None)
        self.assertEqual((r["status"], r["reason"]), (doctor.OFF, "sender confirm: off (config sender_confirm)"))

    def test_a_failed_send_in_the_log_says_the_new_sender_did_not_reach_you(self):
        self.log([log_row(AT + 60, "log (telegram rc=1)")])
        r = self.row()
        self.assertEqual(r["status"], doctor.MISSING)
        self.assertIn("the new sender did not reach you", r["reason"])
        self.assertIn("push via", r["reason"])
        self.log([log_row(AT + 60, "log (no sender profile)")])
        self.assertIn("did not reach you", self.row()["reason"])

    def test_a_held_row_says_it_waits(self):
        self.log([log_row(AT + 60, "held (sleep mode)", body=job.BODY)])
        r = self.row()
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertIn("waits", r["reason"])
        self.assertIn("Sleep mode", r["reason"])

    def test_a_delivered_row_says_it_reached_you_and_the_newest_row_wins(self):
        self.log([log_row(AT + 60, "log (telegram rc=1)"), log_row(AT + 600, "telegram")])
        r = self.row()
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertTrue(r["reason"].startswith("sender confirm: the new sender reached you"), r["reason"])
        self.assertTrue(r["reason"].endswith("; write mode"), r["reason"])

    def test_rows_before_the_reply_or_of_other_messages_do_not_count(self):
        self.log([log_row(AT - 600, "telegram"), log_row(AT + 60, "telegram", title="Pushes are back"),
                  log_row(AT + 90, "telegram", body="Something else")])
        r = self.row()
        self.assertIn("waiting: the sender changed; the next pass sends the confirmation", r["reason"])

    def test_without_a_push_log_the_mark_is_the_fallback(self):
        for outcome, said, status in ((job.FAILED, "did not reach you", doctor.MISSING),
                                      (job.HELD, "waits", doctor.LIVE),
                                      (job.TOLD, "reached you", doctor.LIVE),
                                      (job.DROPPED, "not proven", doctor.LIVE)):
            self.mark(outcome)
            r = self.row(log=None)
            self.assertIn(said, r["reason"], outcome)
            self.assertEqual(r["status"], status, outcome)
        self.mark(job.TOLD, reply_at=AT - H)              # a mark for an older reply says nothing about this one
        self.assertIn("waiting", self.row(log=None)["reason"])

    def test_nothing_to_confirm_a_late_change_or_an_env_sender(self):
        (self.st / push_sender.REPLY_FILE).unlink()
        self.assertEqual(self.row()["reason"], "sender confirm: no sender change to confirm; write mode")
        (self.st / push_sender.REPLY_FILE).write_text(json.dumps({"profile": PROFILE, "at": AT}))
        late = self.row(now=AT + jobs.SENDER_CONFIRM_STALE_S + H)
        self.assertIn("never confirmed", late["reason"])
        env = self.row(env={"KEVIN_PUSH_PROFILE": "pinned"})
        self.assertIn("KEVIN_PUSH_PROFILE is set and still wins", env["reason"])
        self.assertIn("dry run mode", self.row(mode="dry_run")["reason"])

    def test_report_has_the_row_once_after_the_sender_ingest_and_the_fit_import(self):
        with mock.patch.object(doctor, "sender_confirm_row", wraps=doctor.sender_confirm_row) as spy:
            rows = doctor.report({"sender_confirm": "off", "state": str(self.st)}, NOW)
        names = [r["name"] for r in rows]
        self.assertEqual(names.count(doctor.SENDER_CONFIRM_ROW), 1)
        self.assertEqual(names.index(doctor.FIT_IMPORT_ROW), names.index(doctor.SENDER_INGEST_ROW) + 1)
        self.assertEqual(names.index(doctor.SENDER_CONFIRM_ROW), names.index(doctor.FIT_IMPORT_ROW) + 1)
        self.assertEqual(spy.call_count, 1)


if __name__ == "__main__":
    unittest.main()
