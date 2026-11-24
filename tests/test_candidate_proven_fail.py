"""A "maybe" sender that already failed is not offered again, and the push sender row says "missing:" once.

push_sender.candidates calls a profile a maybe when readiness cannot tell whether it has a Telegram bot (a secret
source). The sender ingest applies a ``push via <name>`` reply for a maybe and keeps ``applied_unknown: true`` in its
mark; when that reply's one confirmation then fails to send, the profile is proven unable to send
(push_recovery.proven_failed: the same condition as push_recovery.UNKNOWN_FAILED, read from the mark's flag, the
profile push-sender.json already holds and the confirmation's outcome; nothing new is stored). The push recovery
words and the doctor's sender candidates row then drop it from the maybes and say one already failed. A READY
profile is still offered, and a later applied reply clears it.

Separately, the doctor's push sender row used to print "missing: missing: the sender profile does not exist".

Synthetic Hermes homes (made-up profile names, a placeholder token), synthetic state dirs and a synthetic
kevin-push log at a fixed made-up clock. Nothing is sent and no process is started.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import doctor, push_recovery as pr, push_sender as ps  # noqa: E402
from limitless import sender_confirm_job as confirm_job, sender_reply as sr  # noqa: E402
from hermes_profile_fixture import ready_profile  # noqa: E402

NOW = 1894708800.0   # a fixed made-up clock
H = 3600.0
FAIL = ps.NO_SENDER_HOW
PUSH_LOG = "push-log.jsonl"
SECRET_YAML = "secrets:\n  telegram:\n    source: synthetic-vault\n"
MAYBE_DELTA = "maybe: delta (keeps its token in a secret source)"
NONE_LEFT = "maybe: none left (one already failed to send)"
NO_MAYBE_LEFT = "; no profile left that may reach Telegram (one already failed to send)"


def log_row(at, how, title="Wake-up brief", body="Synthetic body."):
    return {"at": int(at), "tag": "limitless", "cls": "report", "title": title, "body": body, "how": how}


def confirmation(at, how):
    return log_row(at, how, confirm_job.TITLE_SENT, confirm_job.BODY)


class Home(unittest.TestCase):
    """A synthetic Hermes home whose root (``default``) has no bot, a state dir and an open push outage."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.hermes = self.dir / "hermes"
        (self.hermes / "profiles").mkdir(parents=True)
        (self.hermes / "config.yaml").write_text("model: synthetic\n")
        self.st = self.dir / "state"
        self.st.mkdir()
        self.env = child_env({"HERMES_HOME": str(self.hermes), "LIMITLESS_STATE": str(self.st)})
        self.cfg = {"push_profile": "gone", "push_to": "telegram", "push_log": PUSH_LOG, "sender_confirm": "write"}
        self.rows = [log_row(NOW - 5 * H, "telegram"), log_row(NOW - 3 * H, FAIL), log_row(NOW - 2 * H, FAIL)]
        self.write_log()

    def vault(self, name):
        home = self.hermes / "profiles" / name
        home.mkdir(parents=True)
        (home / "config.yaml").write_text(SECRET_YAML)

    def ready(self, name):
        ready_profile(self.hermes / "profiles" / name)

    def write_log(self, extra=()):
        self.rows = self.rows + list(extra)
        (self.st / PUSH_LOG).write_text("".join(json.dumps(r) + "\n" for r in self.rows))

    def applied(self, name, at, unknown=True):
        """push-sender.json and the ingest mark as a write pass leaves them after applying ``push via <name>``."""
        sr.write_reply(self.st, name, at)
        sr.write_mark(self.st, {"action": sr.WRITE, "after": at, "applied_unknown": unknown})

    def refused_later(self, at):
        """A later reply refused (no bot): push-sender.json and the flag stay, refused_at moves."""
        sr.write_mark(self.st, {"action": sr.NO_BOT, "after": at, "refused_at": at,
                                "applied_unknown": sr.applied_unknown(self.st)})

    def failed_delta(self):
        self.vault("delta")
        self.applied("delta", NOW - 90 * 60)
        self.write_log([confirmation(NOW - 80 * 60, "log (telegram rc=1)")])
        self.refused_later(NOW - 30 * 60)

    def stage(self):
        return pr.stage(self.st, self.rows, self.cfg, NOW, env=self.env)

    def row(self):
        return doctor.sender_candidates_row(self.cfg, self.env, state_dir=self.st)


class BeforeAnyFailure(Home):
    def test_a_maybe_is_listed_in_the_words_and_the_row(self):
        self.vault("delta")
        self.assertEqual(self.stage(), (pr.MISSING, pr.WAITING_REPLY + "; profiles that may reach Telegram: delta"))
        self.assertEqual((self.row()["status"], self.row()["reason"]), (doctor.MISSING, MAYBE_DELTA))
        self.assertIsNone(pr.proven_failed(self.st, self.cfg))

    def test_applied_but_not_failed_yet_still_lists_it(self):
        self.vault("delta")
        self.applied("delta", NOW - 90 * 60)
        self.refused_later(NOW - 30 * 60)
        self.assertEqual(self.stage()[1], pr.REFUSED + "; profiles that may reach Telegram: delta")
        self.assertEqual(self.row()["reason"], MAYBE_DELTA)


class AfterTheFailure(Home):
    def test_the_failed_maybe_is_not_offered_and_the_words_say_so(self):
        self.failed_delta()
        self.assertEqual(pr.proven_failed(self.st, self.cfg), "delta")
        self.assertEqual(self.stage(), (pr.MISSING, pr.REFUSED + NO_MAYBE_LEFT))
        r = self.row()
        self.assertEqual((r["status"], r["reason"]), (doctor.MISSING, NONE_LEFT))

    def test_the_confirmation_mark_alone_counts_too(self):
        self.vault("delta")
        self.applied("delta", NOW - 90 * 60)
        (self.st / confirm_job.MARK).write_text(json.dumps({"reply_at": NOW - 90 * 60,
                                                            "outcome": confirm_job.FAILED, "ran_at": NOW - H}))
        self.refused_later(NOW - 30 * 60)
        self.assertEqual(self.stage()[1], pr.REFUSED + NO_MAYBE_LEFT)
        self.assertEqual(self.row()["reason"], NONE_LEFT)

    def test_a_ready_profile_is_still_offered(self):
        self.failed_delta()
        self.ready("alpha")
        self.assertEqual(self.stage()[1], pr.REFUSED + "; ready profiles: alpha")
        r = self.row()
        self.assertEqual((r["status"], r["reason"]), (doctor.LIVE, "ready: alpha; " + NONE_LEFT))

    def test_another_maybe_is_still_offered(self):
        self.failed_delta()
        self.vault("eta")
        self.assertEqual(self.stage()[1], pr.REFUSED + "; profiles that may reach Telegram: eta")
        self.assertEqual(self.row()["reason"], "maybe: eta (keeps its token in a secret source)")

    def test_the_report_row_reads_the_state_dir(self):
        self.failed_delta()
        cfg = dict(self.cfg, state=str(self.st))
        cfg_path = self.dir / "config.json"
        cfg_path.write_text(json.dumps(cfg))
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("LIMITLESS_", "KEVIN_PUSH_", "HERMES_"))}
        clean.update(HOME=str(self.dir), LIMITLESS_CONFIG=str(cfg_path), HERMES_HOME=str(self.hermes))
        with mock.patch.dict(os.environ, clean, clear=True):
            rows = doctor.report(cfg, NOW)
        got = {r["name"]: r["reason"] for r in rows}
        self.assertEqual(got[doctor.SENDER_CANDIDATES_ROW], NONE_LEFT)

    def test_the_words_hold_no_digit_or_path(self):
        for w in (NO_MAYBE_LEFT, NONE_LEFT, pr.NO_MAYBE_LEFT, doctor.CANDIDATES_FAILED):
            self.assertIsNone(re.search(r"\d|/", w))
        self.assertEqual(pr.NO_MAYBE_LEFT, NO_MAYBE_LEFT)


class NotProven(Home):
    def test_a_ready_reply_that_failed_drops_nothing(self):
        self.vault("delta")
        self.applied("delta", NOW - 90 * 60, unknown=False)
        self.write_log([confirmation(NOW - 80 * 60, "log (telegram rc=1)")])
        self.refused_later(NOW - 30 * 60)
        self.assertIsNone(pr.proven_failed(self.st, self.cfg))
        self.assertEqual(self.row()["reason"], MAYBE_DELTA)

    def test_held_by_sleep_mode_drops_nothing(self):
        self.vault("delta")
        self.applied("delta", NOW - 90 * 60)
        self.write_log([confirmation(NOW - 80 * 60, "held (sleep mode)")])
        self.refused_later(NOW - 30 * 60)
        self.assertEqual(self.stage()[1], pr.REFUSED + "; profiles that may reach Telegram: delta")

    def test_a_later_applied_ready_reply_clears_it(self):
        self.failed_delta()
        self.ready("alpha")
        self.applied("alpha", NOW - 20 * 60, unknown=False)
        self.assertIsNone(pr.proven_failed(self.st, self.cfg))
        self.assertEqual(self.row()["reason"], "ready: alpha; " + MAYBE_DELTA)

    def test_no_push_log_or_no_state_dir_drops_nothing(self):
        self.failed_delta()
        self.assertIsNone(pr.proven_failed(None, self.cfg))
        self.assertIsNone(pr.proven_failed(self.st, {}))  # no push_log, no confirmation mark
        self.assertEqual(doctor.sender_candidates_row(self.cfg, self.env)["reason"], MAYBE_DELTA)


class NothingNewStored(Home):
    def test_the_mark_and_the_reply_file_keep_their_old_keys(self):
        self.failed_delta()
        pr.stage(self.st, self.rows, self.cfg, NOW, env=self.env)
        self.row()
        mark = json.loads((self.st / sr.MARK).read_text())
        self.assertLessEqual(set(mark), {"row_at", "ran_at", "mode", "action", "after", "refused_at",
                                         "applied_unknown"})
        self.assertNotIn("delta", (self.st / sr.MARK).read_text())
        self.assertEqual(set(json.loads((self.st / ps.REPLY_FILE).read_text())), {"profile", "at"})
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), sorted([PUSH_LOG, sr.MARK, ps.REPLY_FILE]))


class PushSenderRow(Home):
    def test_a_missing_profile_says_missing_once(self):
        r = doctor.push_sender_row({"push_profile": "gone"}, self.env)
        self.assertEqual((r["status"], r["reason"]), (doctor.MISSING, "the sender profile does not exist"))
        self.assertEqual(doctor.text([r]).strip(), "push sender: missing: the sender profile does not exist")
        self.assertNotIn("missing: missing:", doctor.text([r]))

    def test_other_callers_keep_the_constant(self):
        self.assertEqual(ps.MISSING, "missing: the sender profile does not exist")
        self.assertEqual(ps.readiness({"push_profile": "gone"}, self.env), ps.MISSING)

    def test_other_reasons_are_unchanged(self):
        r = doctor.push_sender_row({"push_profile": "gone", "push_to": "discord:ops"},
                                   dict(self.env, HERMES_HOME=str(self.dir / "nowhere")))
        self.assertEqual(r["reason"], "unknown: the Hermes home does not exist")


class Docs(unittest.TestCase):
    def test_doctor_md_says_it(self):
        text = (ROOT / "docs" / "doctor.md").read_text()
        self.assertIn(NONE_LEFT, text)
        self.assertIn(NO_MAYBE_LEFT.lstrip("; "), text)
        self.assertNotIn("missing: missing:", text)

    def test_the_reply_doc_says_it(self):
        text = (ROOT / "docs" / "push-sender-reply.md").read_text()
        self.assertIn("one already failed to send", text)


if __name__ == "__main__":
    unittest.main()
