"""limitless-doctor's "push recovery" row: where a push-outage recovery stands, in words, from kevin-push's log
(config push_log), push-sender.json, sender-confirm.json and outage-recap.json.

    no outage -> pushes failing, no reply -> sender set, confirmation not delivered -> pushes back, recap waits
    -> recap sent (or settled without one)

Synthetic state dirs and synthetic push log rows only (made-up titles, a made-up profile name). Read-only: the
row writes nothing.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import doctor, jobs, push_recovery as pr, push_sender  # noqa: E402
from limitless import outage_recap_job as recap_job  # noqa: E402
from limitless import sender_confirm_job as confirm_job  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 1894708800.0   # a fixed made-up clock
H = 3600.0
FAIL = push_sender.NO_SENDER_HOW          # "log (no sender profile)"
PUSH_LOG = "push-log.jsonl"
NO_OUTAGE = "no outage: pushes are reaching you"
WAITING_REPLY = "pushes are failing; waiting for a sender reply"
NOT_DELIVERED = "sender set from your reply; the confirmation has not been delivered yet ({})"
RECAP_WAITS = "pushes are back; the recap waits for the next pass"
RECAP_SENT = "pushes are back; recap sent"
SETTLED = "pushes are back; settled without a recap"


def row(at, how, title="Wake-up brief", body="Synthetic body."):
    return {"at": int(at), "tag": "limitless", "cls": "report", "title": title, "body": body, "how": how}


def confirmation(at, how):
    return row(at, how, confirm_job.TITLE_SENT, confirm_job.BODY)


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.st = Path(tmp.name) / "state"
        self.st.mkdir()
        self.cfg = {"push_log": PUSH_LOG, "sender_confirm": "write", "outage_recap": "write"}
        self.first = NOW - 3 * H
        self.outage = [row(NOW - 5 * H, "telegram"), row(self.first, FAIL), row(NOW - 2 * H, FAIL, "MIQ for tonight?")]

    def reply(self, at):
        (self.st / push_sender.REPLY_FILE).write_text(json.dumps({"profile": "sender-synth", "at": at}))

    def confirm_mark(self, reply_at, outcome, ran_at):
        (self.st / confirm_job.MARK).write_text(json.dumps({"reply_at": reply_at, "outcome": outcome,
                                                            "ran_at": ran_at}))

    def recap_mark(self, outcome, first_at=None):
        key = f"outage_recap:{int(self.first if first_at is None else first_at)}"
        (self.st / recap_job.MARK).write_text(json.dumps({"key": key, "outcome": outcome, "at": NOW - 60}))

    def stage(self, rows, cfg=None, now=NOW):
        return pr.stage(self.st, rows, self.cfg if cfg is None else cfg, now)

    def write_log(self, rows):
        (self.st / PUSH_LOG).write_text("".join(json.dumps(r) + "\n" for r in rows))

    def doctor_row(self, cfg=None):
        return doctor.push_recovery_row(StateReader(self.st), self.cfg if cfg is None else cfg, NOW)


class Stages(Case):
    def test_no_outage_is_live(self):
        self.assertEqual(self.stage([row(NOW - H, "telegram")]), (pr.LIVE, NO_OUTAGE))
        self.assertEqual(self.stage([]), (pr.LIVE, NO_OUTAGE))

    def test_one_failed_push_is_not_an_outage(self):
        self.assertEqual(self.stage([row(NOW - 2 * H, "telegram"), row(NOW - H, FAIL)]), (pr.LIVE, NO_OUTAGE))

    def test_an_outage_closed_before_the_recaps_stale_window_is_no_outage(self):
        old = NOW - jobs.OUTAGE_RECAP_STALE_S - 3 * H
        rows = [row(old, FAIL), row(old + 60, FAIL), row(old + 2 * H, "telegram")]
        self.assertEqual(self.stage(rows), (pr.LIVE, NO_OUTAGE))

    def test_pushes_failing_and_no_reply_is_missing(self):
        self.assertEqual(self.stage(self.outage), (pr.MISSING, WAITING_REPLY))

    def test_a_reply_older_than_the_outage_is_not_its_reply(self):
        self.reply(self.first - H)
        self.assertEqual(self.stage(self.outage), (pr.MISSING, WAITING_REPLY))

    def test_reply_applied_and_no_confirmation_yet(self):
        self.reply(NOW - 150)
        self.assertEqual(self.stage(self.outage), (pr.STALE, NOT_DELIVERED.format("not sent yet")))

    def test_reply_applied_and_the_confirmation_held_by_sleep_mode(self):
        self.reply(NOW - 150)
        rows = self.outage + [confirmation(NOW - 100, "held (sleep mode)")]
        self.assertEqual(self.stage(rows), (pr.STALE, NOT_DELIVERED.format("held while Sleep mode was on")))

    def test_the_held_confirmation_read_from_the_mark_without_a_log_row(self):
        self.reply(NOW - 150)
        self.confirm_mark(NOW - 150, confirm_job.HELD, NOW - 100)
        self.assertEqual(self.stage(self.outage), (pr.STALE, NOT_DELIVERED.format("held while Sleep mode was on")))

    def test_reply_applied_and_the_confirmation_failed_to_send(self):
        self.reply(NOW - 150)
        rows = self.outage + [confirmation(NOW - 100, "log (telegram rc=1)")]
        self.assertEqual(self.stage(rows), (pr.STALE, NOT_DELIVERED.format("failed to send")))

    def test_a_failed_mark_says_failed_to_send(self):
        self.reply(NOW - 150)
        self.confirm_mark(NOW - 150, confirm_job.FAILED, NOW - 100)
        self.assertEqual(self.stage(self.outage), (pr.STALE, NOT_DELIVERED.format("failed to send")))

    def test_a_mark_for_an_older_reply_does_not_count(self):
        self.reply(NOW - 150)
        self.confirm_mark(NOW - 9 * H, confirm_job.HELD, NOW - 8 * H)
        self.assertEqual(self.stage(self.outage), (pr.STALE, NOT_DELIVERED.format("not sent yet")))

    def back(self):
        self.reply(NOW - 150)
        return self.outage + [confirmation(NOW - 100, "telegram")]

    def test_confirmation_delivered_and_the_recap_waits(self):
        self.assertEqual(self.stage(self.back()), (pr.STALE, RECAP_WAITS))

    def test_the_recap_off_or_in_dry_run_mode_says_so(self):
        self.assertEqual(self.stage(self.back(), dict(self.cfg, outage_recap="off")),
                         (pr.STALE, "pushes are back; the recap is off"))
        self.assertEqual(self.stage(self.back(), dict(self.cfg, outage_recap="dry_run")),
                         (pr.STALE, "pushes are back; the recap is in dry run mode"))

    def test_recap_sent_is_live(self):
        rows = self.back()
        self.recap_mark(recap_job.TOLD)
        self.assertEqual(self.stage(rows), (pr.LIVE, RECAP_SENT))

    def test_settled_without_a_recap_is_live(self):
        rows = self.back()
        self.recap_mark(recap_job.DROPPED)
        self.assertEqual(self.stage(rows), (pr.LIVE, SETTLED))

    def test_a_recap_mark_for_an_older_outage_does_not_count(self):
        rows = self.back()
        self.recap_mark(recap_job.TOLD, first_at=NOW - 40 * H)
        self.assertEqual(self.stage(rows), (pr.STALE, RECAP_WAITS))

    def test_no_push_log_is_missing_with_a_reason(self):
        status, words = self.stage(None)
        self.assertEqual(status, pr.MISSING)
        self.assertIn("no push log set", words)

    def test_the_statuses_are_the_doctors(self):
        self.assertEqual((pr.LIVE, pr.STALE, pr.MISSING), (doctor.LIVE, doctor.STALE, doctor.MISSING))


class Row(Case):
    def test_the_row_reads_the_log_from_config_push_log(self):
        self.write_log(self.outage)
        self.assertEqual(self.doctor_row(), {"name": "push recovery", "kind": "source", "status": "missing",
                                             "reason": WAITING_REPLY})

    def test_no_push_log_set_is_missing_with_a_reason(self):
        r = self.doctor_row({})
        self.assertEqual(r["status"], doctor.MISSING)
        self.assertEqual(r["reason"], "unknown: no push log set (config push_log)")

    def test_a_push_log_that_cannot_be_read_is_missing_with_a_reason(self):
        r = self.doctor_row()
        self.assertEqual(r["status"], doctor.MISSING)
        self.assertEqual(r["reason"], "unknown: the push log could not be read")

    def test_every_stage_holds_no_digit_path_or_profile_name(self):
        seen = []
        for rows, setup in ((self.outage, None), (self.outage, lambda: self.reply(NOW - 150)),
                            (self.outage + [confirmation(NOW - 100, "held (sleep mode)")], None),
                            (self.outage + [confirmation(NOW - 100, "telegram")], None),
                            (self.outage + [confirmation(NOW - 100, "telegram")],
                             lambda: self.recap_mark(recap_job.TOLD))):
            if setup:
                setup()
            self.write_log(rows)
            r = self.doctor_row()
            seen.append(r["reason"])
            self.assertIsNone(re.search(r"\d", r["reason"]), r)
            for word in ("sender-synth", str(self.st), "/", ".json"):
                self.assertNotIn(word, r["reason"])
        self.assertEqual(len(set(seen)), len(seen), seen)

    def test_the_row_writes_nothing(self):
        self.reply(NOW - 150)
        self.confirm_mark(NOW - 150, confirm_job.HELD, NOW - 100)
        self.write_log(self.outage + [confirmation(NOW - 100, "held (sleep mode)")])

        def snap():
            return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.st.iterdir()}
        before = snap()
        for cfg in (self.cfg, {}, dict(self.cfg, outage_recap="off")):
            self.doctor_row(cfg)
        self.assertEqual(snap(), before)

    def test_kind_source_is_never_counted_by_strict(self):
        self.write_log(self.outage)
        r = self.doctor_row()
        self.assertFalse(doctor.strict_failed([r]))

    def test_right_after_the_push_sender_row_in_the_report(self):
        self.write_log(self.outage)
        cfg_path = self.st.parent / "config.json"
        cfg = dict(self.cfg, state=str(self.st))
        cfg_path.write_text(json.dumps(cfg))
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("LIMITLESS_", "KEVIN_PUSH_", "HERMES_"))}
        clean.update(LIMITLESS_CONFIG=str(cfg_path), LIMITLESS_STATE=str(self.st))
        with mock.patch.dict(os.environ, clean, clear=True):
            rows = doctor.report(cfg, NOW)
        names = [r["name"] for r in rows]
        self.assertEqual(names.count(doctor.PUSH_RECOVERY_ROW), 1)
        self.assertEqual(names.index(doctor.PUSH_RECOVERY_ROW), names.index(doctor.PUSH_SENDER_ROW) + 1)
        self.assertEqual(names.index(doctor.SLEEP_MODE_ROW), names.index(doctor.PUSH_RECOVERY_ROW) + 1)
        self.assertEqual(rows[names.index(doctor.PUSH_RECOVERY_ROW)]["reason"], WAITING_REPLY)



class Docs(unittest.TestCase):
    def test_the_doc_shows_the_examples_real_output_for_every_stage(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "push_recovery_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = (ROOT / "docs" / "doctor.md").read_text()
        self.assertIn(r.stdout, re.findall(r"```text\n(.*?)```", doc, re.S))
        for words in (NO_OUTAGE, WAITING_REPLY, RECAP_WAITS, RECAP_SENT, "held while Sleep mode was on",
                      "failed to send", "not sent yet", "the recap is off"):
            self.assertIn(words, r.stdout)
        self.assertNotIn("sender-synth", r.stdout)
        self.assertIn("## Push recovery row", doc)
        self.assertIn("`push recovery`, right after the push sender row", doc)


if __name__ == "__main__":
    unittest.main()
