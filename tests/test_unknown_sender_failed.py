"""An applied "unknown" sender whose confirmation fails: the push recovery says the named profile may have no bot.

The sender ingest refuses a ``push via <name>`` reply only on a definite no from push_sender.readiness; an unknown
answer (the profile may keep its token in a secret source) is applied. When that profile in fact cannot send, the
one confirmation push fails. The ingest mark keeps ``applied_unknown: true`` (a boolean only) for such a reply, and
push_recovery then says UNKNOWN_FAILED instead of the plain "failed to send", so the owner knows to name another
profile. Held by Sleep mode or not sent yet keeps the old words; a READY reply that fails keeps them too; a later
applied reply clears it. push_reach (the state card and limitless_status) carries the same words.

Synthetic state dirs, a synthetic Hermes home (made-up profile names, a token placeholder) and synthetic
kevin-push log rows only, at a fixed made-up clock. Nothing is sent and no process is started.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import doctor, jobs, push_reach, push_recovery as pr, push_sender  # noqa: E402
from limitless import sender_ingest_job as ingest_job, sender_reply as sr  # noqa: E402
from limitless import sender_confirm_job as confirm_job  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 1894708800.0   # a fixed made-up clock
H = 3600.0
FAIL = push_sender.NO_SENDER_HOW
PUSH_LOG = "push-log.jsonl"
NEW_WORDS = ("pushes are failing; the profile you named was set but could not send, so it may have no Telegram "
             "bot; reply push via another profile")
OLD_FAILED = "sender set from your reply; the confirmation has not been delivered yet (failed to send)"
OLD_HELD = "sender set from your reply; the confirmation has not been delivered yet (held while Sleep mode was on)"
OLD_NOT_SENT = "sender set from your reply; the confirmation has not been delivered yet (not sent yet)"
VAULT, GOOD = "sender-vault", "sender-synth"


def row(at, how, title="Wake-up brief", body="Synthetic body."):
    return {"at": int(at), "tag": "limitless", "cls": "report", "title": title, "body": body, "how": how}


def confirmation(at, how):
    return row(at, how, confirm_job.TITLE_SENT, confirm_job.BODY)


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.hermes = self.dir / "hermes"
        good = self.hermes / "profiles" / GOOD
        good.mkdir(parents=True)
        (good / ".env").write_text("TELEGRAM_BOT_TOKEN=placeholder-token-not-real\n"
                                   "TELEGRAM_HOME_CHANNEL=placeholder-chat\n")
        vault = self.hermes / "profiles" / VAULT     # no token in its files; a secret source may hold one
        vault.mkdir(parents=True)
        (vault / "config.yaml").write_text("secrets:\n  vault:\n    kind: placeholder\n")
        self.env = child_env({"HERMES_HOME": str(self.hermes), "LIMITLESS_STATE": str(self.st)})
        self.cfg = {"push_log": PUSH_LOG, "push_to": "telegram", "sender_confirm": "write", "outage_recap": "write"}
        self.first = NOW - 3 * H
        self.outage = [row(NOW - 5 * H, "telegram"), row(self.first, FAIL), row(NOW - 2 * H, FAIL, "MIQ for tonight?")]

    def apply(self, name, at, now=None):
        """One write pass of the sender ingest over the owner's one reply ``push via <name>`` at ``at`` (the
        Hermes session DB read is replaced by that one message)."""
        replies = [(at, f"push via {name}")]
        with mock.patch.object(ingest_job._habit_replies, "replies_from_hermes_db",
                               lambda db, after: [r for r in replies if r[0] > after]):
            return ingest_job.run_ingest(self.st, "hermes.db", NOW - 600, at + 30 if now is None else now,
                                         jobs.SENDER_WRITE, self.env, self.cfg)

    def write_log(self, rows):
        (self.st / PUSH_LOG).write_text("".join(json.dumps(r) + "\n" for r in rows))

    def stage(self, rows):
        return pr.stage(self.st, rows, self.cfg, NOW)


class Mark(Case):
    def test_an_unknown_reply_applied_keeps_applied_unknown_true(self):
        mark, got = self.apply(VAULT, NOW - 150)
        self.assertEqual(got["action"], sr.WRITE)
        self.assertIs(mark["applied_unknown"], True)
        self.assertIs(sr.applied_unknown(self.st), True)
        data = json.loads((self.st / sr.MARK).read_text())
        self.assertIs(data["applied_unknown"], True)
        self.assertNotIn(VAULT, (self.st / sr.MARK).read_text())

    def test_a_ready_reply_applied_keeps_no_flag(self):
        self.apply(GOOD, NOW - 150)
        self.assertNotIn("applied_unknown", json.loads((self.st / sr.MARK).read_text()))
        self.assertIs(sr.applied_unknown(self.st), False)

    def test_a_later_ready_reply_clears_it(self):
        self.apply(VAULT, NOW - 300)
        self.apply(GOOD, NOW - 150)
        self.assertIs(sr.applied_unknown(self.st), False)

    def test_a_pass_with_no_new_reply_or_a_refused_one_keeps_it(self):
        self.apply(VAULT, NOW - 300)
        self.apply(VAULT, NOW - 300, now=NOW - 200)          # nothing new
        self.assertIs(sr.applied_unknown(self.st), True)
        self.apply("sender-nowhere", NOW - 150)               # refused: push-sender.json is unchanged
        self.assertIs(sr.applied_unknown(self.st), True)

    def test_a_broken_or_non_boolean_flag_reads_false(self):
        (self.st / sr.MARK).write_text(json.dumps({"applied_unknown": "yes"}))
        self.assertIs(sr.applied_unknown(self.st), False)
        (self.st / sr.MARK).write_text("{")
        self.assertIs(sr.applied_unknown(self.st), False)


class Stage(Case):
    def test_unknown_applied_and_the_confirmation_failed_says_it_may_have_no_bot(self):
        self.apply(VAULT, NOW - 150)
        rows = self.outage + [confirmation(NOW - 100, "log (telegram rc=1)")]
        self.assertEqual(self.stage(rows), (pr.MISSING, NEW_WORDS))
        self.assertEqual(pr.UNKNOWN_FAILED, NEW_WORDS)

    def test_the_failed_mark_without_a_log_row_counts_too(self):
        self.apply(VAULT, NOW - 150)
        (self.st / confirm_job.MARK).write_text(json.dumps({"reply_at": NOW - 150, "outcome": confirm_job.FAILED,
                                                            "ran_at": NOW - 100}))
        self.assertEqual(self.stage(self.outage), (pr.MISSING, NEW_WORDS))

    def test_ready_applied_and_the_confirmation_failed_keeps_the_old_words(self):
        self.apply(GOOD, NOW - 150)
        rows = self.outage + [confirmation(NOW - 100, "log (telegram rc=1)")]
        self.assertEqual(self.stage(rows), (pr.STALE, OLD_FAILED))

    def test_unknown_applied_and_held_by_sleep_mode_keeps_the_old_words(self):
        self.apply(VAULT, NOW - 150)
        rows = self.outage + [confirmation(NOW - 100, "held (sleep mode)")]
        self.assertEqual(self.stage(rows), (pr.STALE, OLD_HELD))

    def test_unknown_applied_and_not_sent_yet_keeps_the_old_words(self):
        self.apply(VAULT, NOW - 150)
        self.assertEqual(self.stage(self.outage), (pr.STALE, OLD_NOT_SENT))

    def test_a_later_applied_reply_clears_it(self):
        self.apply(VAULT, NOW - 300)
        rows = self.outage + [confirmation(NOW - 250, "log (telegram rc=1)")]
        self.assertEqual(self.stage(rows), (pr.MISSING, NEW_WORDS))
        self.apply(GOOD, NOW - 150)
        self.assertEqual(self.stage(rows), (pr.STALE, OLD_NOT_SENT))
        self.assertEqual(self.stage(rows + [confirmation(NOW - 100, "telegram")])[1],
                         "pushes are back; the recap waits for the next pass")

    def test_a_refusal_after_it_still_says_refused(self):
        self.apply(VAULT, NOW - 300)
        rows = self.outage + [confirmation(NOW - 250, "log (telegram rc=1)")]
        self.apply("sender-nowhere", NOW - 150)
        self.assertEqual(self.stage(rows), (pr.MISSING, pr.REFUSED))

    def test_the_words_hold_no_digit_path_or_profile_name(self):
        self.assertIsNone(re.search(r"\d", NEW_WORDS))
        for w in (VAULT, "/", ".json"):
            self.assertNotIn(w, NEW_WORDS)


class Surfaces(Case):
    def failed(self):
        self.apply(VAULT, NOW - 150)
        self.write_log(self.outage + [confirmation(NOW - 100, "log (telegram rc=1)")])

    def test_the_doctor_row_says_it(self):
        self.failed()
        r = doctor.push_recovery_row(StateReader(self.st), self.cfg, NOW)
        self.assertEqual((r["name"], r["status"], r["reason"]), (doctor.PUSH_RECOVERY_ROW, doctor.MISSING, NEW_WORDS))

    def test_the_card_outage_line_says_it(self):
        self.failed()
        why = push_reach.reason(self.cfg, self.st, date(2030, 1, 15), self.env)
        self.assertEqual(why, push_reach.SENDER_NO_BOT)
        self.assertEqual(push_reach.line(why), "Phone pushes are not reaching you: the profile you named was set "
                                               "but could not send, so it may have no Telegram bot; reply push "
                                               "via another profile")
        self.assertEqual(push_reach.item(why)["value"], push_reach.line(why))

    def test_the_card_keeps_its_words_when_the_reply_was_ready(self):
        self.apply(GOOD, NOW - 150)
        self.write_log(self.outage + [confirmation(NOW - 100, "log (telegram rc=1)")])
        why = push_reach.reason(self.cfg, self.st, date(2030, 1, 15), self.env)
        self.assertNotEqual(why, push_reach.SENDER_NO_BOT)

    def test_the_cache_key_moves_when_the_reply_or_the_mark_changes(self):
        self.failed()
        k1 = push_reach.key(self.cfg, self.st, self.env)
        self.apply(GOOD, NOW - 50, now=NOW - 40)
        self.assertNotEqual(push_reach.key(self.cfg, self.st, self.env), k1)


if __name__ == "__main__":
    unittest.main()
