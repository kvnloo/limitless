"""The owner's "restore <name>" reply, the one the state card asks for when Hermes deleted the sender profile: the
sender ingest job records it (restore-request.json) and every surface says it was asked; the plugin never restores
anything itself.

Synthetic state (tests/fixtures/state), synthetic Hermes homes in a temp dir (the tombstone is Hermes' own format: a
FILE ``profiles/.deleted/<name>`` holding ``deleted\\n``), the synthetic session DB of tests/hermes_db_fixture.py,
made-up profile names (courier, helper), a fixed clock and day, env passed explicitly. Nothing is run or sent and no
process is started.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import card, doctor, push_reach, push_recovery, push_sender, restore_reply, \
    sender_ingest_job, sender_reply  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from hermes_db_fixture import make_db  # noqa: E402
from hermes_profile_fixture import ready_profile  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "state"
UTC = timezone.utc
H = 3600
NOW = 1894708800.0
TODAY = date(2030, 1, 15)
SENDER = "courier"
PREFIX = "Phone pushes are not reaching you: "
DELETED_REASON = "the sender profile was deleted"
RESTORE = "Reply restore courier to bring it back."
ASKED = "Restore asked; it will be done by the operator."
WAITING = "pushes are failing; waiting for a sender reply"
DELETED_TAIL = "; the sender profile was deleted and can be restored"
ASKED_TAIL = "; a restore was asked"
OLD_WORDS = WAITING + DELETED_TAIL + "; no profile can reach Telegram"
RC1 = "log (telegram rc=1)"
FIRST_FAIL = NOW - 6 * H


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_row(at, how="telegram"):
    return {"at": int(at), "tag": "x", "cls": "decision", "title": "Pick one", "how": how,
            "body": "Keep the loop?\nReply: Yes / No"}


# an open outage (WAITING_REPLY) that began at FIRST_FAIL
FAILING = [log_row(NOW - 7 * H), log_row(FIRST_FAIL, RC1), log_row(NOW - 5 * H, RC1)]


def no_process(*a, **k):
    raise AssertionError("a process was started")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.st = root / "st"
        shutil.copytree(FIX, self.st)
        self.hermes = root / "hermes"
        self.profiles = self.hermes / "profiles"
        self.deleted = self.profiles / ".deleted"
        (self.profiles / "other").mkdir(parents=True)
        self.log = self.st / "push-log.jsonl"
        self.cfg_path = root / "config.json"
        self.config()
        self.env = {"HOME": str(root), "HERMES_HOME": str(self.hermes), "LIMITLESS_STATE": str(self.st),
                    "LIMITLESS_CONFIG": str(self.cfg_path)}
        self.r = StateReader(self.st)
        self.req = self.st / restore_reply.REQUEST_FILE
        self.write_log(FAILING)
        (self.st / "runs.jsonl").write_text(json.dumps({"at": iso(NOW - H), "job": "sync", "ok": True,
                                                        "took_s": 9.5}) + "\n")
        for target in ((subprocess, "Popen"), (os, "fork"), (os, "posix_spawn"), (os, "system")):
            if hasattr(*target):
                p = mock.patch.object(*target, side_effect=no_process)
                p.start()
                self.addCleanup(p.stop)

    def config(self, **kw):
        cfg = {"push_profile": SENDER, "push_to": "telegram", "push_log": "push-log.jsonl",
               "hermes_db": "hermes.db", "sender_ingest": "write"}
        cfg.update(kw)
        self.cfg = {k: v for k, v in cfg.items() if v is not None}
        self.cfg_path.write_text(json.dumps(self.cfg))

    def tombstone(self, name=SENDER):
        # Hermes' own format (hermes_constants.mark_named_profile_deleted): a marker FILE holding "deleted\n"
        self.deleted.mkdir(parents=True, exist_ok=True)
        p = self.deleted / name
        p.write_text("deleted\n")
        return p

    def live(self, name):
        return ready_profile(self.profiles / name)

    def write_log(self, rows):
        self.log.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def db(self, messages):
        p = self.st / "hermes.db"
        if p.exists():
            p.unlink()
        make_db(p, messages, started=NOW - 20 * H)

    def ingest(self, now=NOW, dry_run=False):
        return sender_ingest_job.run(self.st, now, dry_run=dry_run, env=self.env, home=Path(self.tmp.name))

    def request(self):
        return json.loads(self.req.read_text()) if self.req.exists() else None

    def put_request(self, at, profile=SENDER):
        self.req.write_text(json.dumps({"profile": profile, "at": at, "seen_at": at + 60}))

    def hint(self):
        return push_reach.hint(self.cfg, self.st, self.env)

    def stage(self):
        return push_recovery.from_state(self.st, self.cfg, NOW, env=self.env)

    def doctor_row(self):
        return doctor.push_recovery_row(self.r, self.cfg, NOW, self.env)["reason"]

    def build(self):
        return card.build(self.r, NOW, TODAY, env=self.env)

    def outage(self, lines=None):
        return [ln for ln in (self.build()["lines"] if lines is None else lines) if ln.startswith(PREFIX)]

    def assertOldWords(self):
        self.assertEqual(self.hint(), RESTORE)
        self.assertEqual(self.stage(), ("missing", OLD_WORDS))
        self.assertEqual(self.doctor_row(), OLD_WORDS)
        self.assertEqual(self.outage(), [PREFIX + DELETED_REASON + ". " + RESTORE])

    def assertAskedWords(self):
        self.assertEqual(self.hint(), ASKED)
        self.assertEqual(self.stage(), ("missing", WAITING + ASKED_TAIL))
        self.assertEqual(self.doctor_row(), WAITING + ASKED_TAIL)
        self.assertEqual(self.outage(), [PREFIX + DELETED_REASON + ". " + ASKED])


class Parse(unittest.TestCase):
    def test_a_whole_restore_message(self):
        for text in ("restore courier", "  Restore   COURIER \n", "RESTORE\tcourier"):
            self.assertEqual(restore_reply.parse(text), SENDER, text)

    def test_anything_else_is_not(self):
        for text in ("restore courier please", "please restore courier", "restore", "restore courier.",
                     "restore courier\nthanks", "Reply restore courier to bring it back.", "push via courier",
                     "restore ../courier", None, 5):
            self.assertIsNone(restore_reply.parse(text), text)


class Records(Base):
    def test_the_reply_for_the_tombstoned_sender_is_recorded_and_acknowledged(self):
        self.tombstone()
        self.db([("user", "restore courier", NOW - 2 * H)])
        self.assertOldWords()
        r = self.ingest()
        self.assertEqual(self.request(), {"profile": SENDER, "at": NOW - 2 * H, "seen_at": NOW})
        self.assertEqual(stat.S_IMODE(self.req.stat().st_mode), 0o600)
        self.assertIn("recorded your restore request", r["reason"])
        self.assertNotRegex(r["reason"], r"\d")
        self.assertNotIn(SENDER, r["reason"])
        self.assertAskedWords()
        self.assertFalse((self.profiles / SENDER).exists(), "nothing is restored")
        self.assertTrue((self.deleted / SENDER).is_file(), "the tombstone is untouched")
        self.assertFalse((self.st / sender_reply.SENDER_FILE).exists(), "the sender is not changed")
        self.assertEqual([p.name for p in self.st.glob(".restore-request.json.*")], [], "no temp file left")

    def test_the_newest_restore_message_wins(self):
        self.tombstone()
        self.db([("user", "restore courier", NOW - 3 * H), ("user", "restore helper", NOW - 2 * H)])
        self.ingest()
        self.assertIsNone(self.request(), "the newest names another profile: no fallback to an older one")

    def test_an_assistant_message_is_not_the_owner(self):
        self.tombstone()
        self.db([("assistant", "restore courier", NOW - 2 * H)])
        self.ingest()
        self.assertIsNone(self.request())


class Ignored(Base):
    def check_ignored(self, messages):
        self.db(messages)
        r = self.ingest()
        self.assertIsNone(self.request())
        self.assertNotIn("restore", r["reason"])

    def test_another_profile(self):
        self.tombstone()
        self.tombstone("helper")
        self.check_ignored([("user", "restore helper", NOW - 2 * H)])
        self.assertOldWords()

    def test_extra_words(self):
        self.tombstone()
        self.check_ignored([("user", "restore courier please", NOW - 2 * H)])
        self.check_ignored([("user", "can you restore courier", NOW - 2 * H)])
        self.assertOldWords()

    def test_a_live_sender(self):
        self.live(SENDER)
        self.check_ignored([("user", "restore courier", NOW - 2 * H)])

    def test_a_missing_sender_without_a_tombstone(self):
        self.check_ignored([("user", "restore courier", NOW - 2 * H)])

    def test_a_request_older_than_the_outage(self):
        self.tombstone()
        self.put_request(FIRST_FAIL - H)
        self.assertOldWords()

    def test_a_request_for_another_profile_on_file(self):
        self.tombstone()
        self.put_request(NOW - 2 * H, profile="helper")
        self.assertOldWords()

    def test_a_broken_request_file(self):
        self.tombstone()
        for text in ("{", "[]", json.dumps({"profile": SENDER, "at": "soon"}), json.dumps({"at": NOW - H})):
            self.req.write_text(text)
            self.assertOldWords()


class Modes(Base):
    def setUp(self):
        super().setUp()
        self.tombstone()
        self.db([("user", "restore courier", NOW - 2 * H)])

    def test_dry_run_writes_no_request(self):
        self.config(sender_ingest="dry_run")
        r = self.ingest()
        self.assertIsNone(self.request())
        self.assertIn("would record your restore request", r["reason"])
        self.assertOldWords()

    def test_off_does_nothing(self):
        self.config(sender_ingest=None)
        self.assertIsNone(self.ingest())
        self.assertIsNone(self.request())
        self.assertFalse((self.st / sender_reply.MARK).exists())

    def test_a_dry_run_of_limitless_jobs_writes_nothing(self):
        self.ingest(dry_run=True)
        self.assertIsNone(self.request())


class LiveAgain(Base):
    def test_once_the_profile_is_back_every_string_is_todays(self):
        self.tombstone()
        self.db([("user", "restore courier", NOW - 2 * H)])
        self.ingest()
        self.assertAskedWords()
        # the operator restores it in Hermes: the tombstone goes and a live profile is back
        (self.deleted / SENDER).unlink()
        self.live(SENDER)
        self.assertIsNotNone(self.request(), "the request stays on file, stale")
        with_request = (self.hint(), self.stage(), self.doctor_row(), self.outage())
        self.assertNotIn(ASKED, self.build()["text"])
        self.assertNotIn(ASKED_TAIL, self.doctor_row())
        self.req.unlink()
        self.assertEqual((self.hint(), self.stage(), self.doctor_row(), self.outage()), with_request,
                         "byte for byte the words with no request at all")

    def test_a_closed_outage_keeps_the_recap_flow(self):
        self.tombstone()
        self.put_request(NOW - 2 * H)
        self.write_log(FAILING + [log_row(NOW - H)])
        with_request = self.stage()
        self.req.unlink()
        self.assertEqual(self.stage(), with_request)


class Card(Base):
    def test_no_digit_or_path_on_the_card(self):
        self.tombstone()
        self.put_request(NOW - 2 * H)
        c = self.build()
        self.assertEqual(self.outage(c["lines"]), [PREFIX + DELETED_REASON + ". " + ASKED])
        self.assertEqual(re.findall(r"\d", c["text"]), [])
        self.assertNotIn(self.tmp.name, c["text"])
        for words in (ASKED, ASKED_TAIL, push_reach.RESTORE_ASKED, push_recovery.RESTORE_ASKED):
            self.assertNotRegex(words, r"[\d/]")
        self.assertEqual(push_reach.RESTORE_ASKED, ASKED)
        self.assertEqual(push_recovery.RESTORE_ASKED, ASKED_TAIL)

    def test_the_key_holds_the_request_mtime(self):
        self.tombstone()
        k0 = push_reach.key(self.cfg, self.st, self.env)
        self.put_request(NOW - 2 * H)
        k1 = push_reach.key(self.cfg, self.st, self.env)
        self.assertNotEqual(k1, k0)
        st = self.req.stat()
        os.utime(self.req, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
        self.assertNotEqual(push_reach.key(self.cfg, self.st, self.env), k1)

    def test_a_recorded_request_rebuilds_the_cached_card(self):
        self.tombstone()
        c = card.CardCache()
        self.assertIn(PREFIX + DELETED_REASON + ". " + RESTORE, c.get(self.r, NOW, TODAY, env=self.env))
        builds = c.builds
        self.put_request(NOW - 2 * H)
        self.assertIn(PREFIX + DELETED_REASON + ". " + ASKED, c.get(self.r, NOW, TODAY, env=self.env))
        self.assertEqual(c.builds, builds + 1)


class NothingSent(Base):
    def test_the_job_starts_no_process_and_sends_nothing(self):
        self.tombstone()
        self.db([("user", "restore courier", NOW - 2 * H)])
        before = self.log.read_text()
        self.ingest()     # setUp patched Popen, fork, posix_spawn and system to fail the test
        self.assertEqual(self.log.read_text(), before, "nothing logged as sent")
        self.assertIsNotNone(self.request())


if __name__ == "__main__":
    unittest.main()
