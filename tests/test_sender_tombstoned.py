"""A tombstoned sender profile (Hermes' ``hermes profile delete`` writes a marker file ``<home>/profiles/.deleted/<name>``) is
named as deleted, with restoring it as the fix: push_sender.tombstoned, the doctor's push sender row, push_reach's
reason and hint, and the push recovery WAITING_REPLY words. Every other case keeps today's words byte for byte.

Synthetic state (tests/fixtures/state), synthetic Hermes homes in a temp dir, made-up profile names (courier,
helper, relay), a made-up token, synthetic kevin-push logs, a fixed clock and day, env passed explicitly. Nothing
is run or sent and no process is started.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card, context_packet, doctor, push_reach, push_recovery, push_sender, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
NOW = 1894708800.0
TODAY = date(2030, 1, 15)
DAY = TODAY - timedelta(days=3)
SENDER = "courier"
READY_ENV = "TELEGRAM_BOT_TOKEN=made-up-token\nTELEGRAM_HOME_CHANNEL=made-up-chat\n"
PREFIX = "Phone pushes are not reaching you: "
DELETED_ROW = "the sender profile was deleted; restoring it should bring pushes back"
MISSING_ROW = "the sender profile does not exist"
DELETED_REASON = "the sender profile was deleted"
MISSING_REASON = "the sender profile is missing"
RESTORE = "Reply restore courier to bring it back."
RESTORE_GENERIC = "Restore the deleted sender profile to bring it back."
GENERIC = "Reply with a profile that has a Telegram bot."
WAITING = "pushes are failing; waiting for a sender reply"
DELETED_TAIL = "; the sender profile was deleted and can be restored"
RC1 = "log (telegram rc=1)"


def log_row(hour, how="telegram"):
    at = int(datetime(DAY.year, DAY.month, DAY.day, hour, 0, tzinfo=timezone.utc).timestamp())
    return {"at": at, "tag": "x", "cls": "decision", "title": "Pick one", "how": how,
            "body": "Keep the loop?\nReply: Yes / No"}


FAILING_LAST = [log_row(10), log_row(11, RC1), log_row(12, RC1)]    # an open outage: WAITING_REPLY


def no_process(*a, **k):
    raise AssertionError("a process was started")


class Base(unittest.TestCase):
    sender_name = SENDER

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
        self.cfg = {"push_profile": self.sender_name, "push_to": "telegram", "push_log": "push-log.jsonl"}
        self.cfg_path.write_text(json.dumps(self.cfg))
        self.env = {"HOME": str(root), "HERMES_HOME": str(self.hermes), "LIMITLESS_STATE": str(self.st),
                    "LIMITLESS_CONFIG": str(self.cfg_path)}
        self.r = StateReader(self.st)
        for target in ((subprocess, "Popen"), (os, "fork"), (os, "posix_spawn"), (os, "system")):
            if hasattr(*target):
                p = mock.patch.object(*target, side_effect=no_process)
                p.start()
                self.addCleanup(p.stop)

    def live(self, name, ready=True):
        p = self.profiles / name
        p.mkdir(parents=True, exist_ok=True)
        if ready:
            (p / ".env").write_text(READY_ENV)
        return p

    def tombstone(self, name=None):
        # Hermes' own format (hermes_constants.mark_named_profile_deleted): a marker FILE
        # profiles/.deleted/<name> holding "deleted\n"; the profile dir itself is removed.
        self.deleted.mkdir(parents=True, exist_ok=True)
        p = self.deleted / (name or self.sender_name)
        p.write_text("deleted\n")
        return p

    def write_log(self, rows):
        self.log.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def tombstoned(self):
        return push_sender.tombstoned(self.cfg, self.env)

    def row(self):
        return doctor.push_sender_row(self.cfg, self.env)

    def reason(self):
        return push_reach.reason(self.cfg, self.st, TODAY, self.env)

    def hint(self):
        return push_reach.hint(self.cfg, self.st, self.env)

    def stage(self):
        return push_recovery.from_state(self.st, self.cfg, NOW, env=self.env)

    def build(self):
        return card.build(self.r, NOW, TODAY, env=self.env)

    def outage(self, lines=None):
        return [ln for ln in (self.build()["lines"] if lines is None else lines) if ln.startswith(PREFIX)]

    @staticmethod
    def bump(p):
        st = p.stat()
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))


class Tombstoned(Base):
    def test_a_tombstoned_sender_is_tombstoned(self):
        self.tombstone()
        self.assertIs(self.tombstoned(), True)

    def test_a_missing_sender_without_a_tombstone_is_not(self):
        self.assertIs(self.tombstoned(), False)
        self.deleted.mkdir()
        self.tombstone("helper")      # another profile's tombstone says nothing about the sender
        self.assertIs(self.tombstoned(), False)

    def test_a_live_dir_of_the_same_name_wins(self):
        self.tombstone()
        self.live(SENDER)
        self.assertIs(self.tombstoned(), False)

    def test_default_and_unresolvable_names_are_never_tombstoned(self):
        self.tombstone("default")
        self.cfg["push_profile"] = "default"
        self.assertIs(self.tombstoned(), False)
        self.cfg["push_profile"] = "../courier"
        self.tombstone()
        self.assertIs(self.tombstoned(), False)

    def test_hermes_marker_file_is_a_tombstone(self):
        # hermes_constants.named_profile_is_deleted is profile_tombstone_path(...).exists(): a file
        self.deleted.mkdir()
        (self.deleted / SENDER).write_text("deleted\n")
        self.assertIs(self.tombstoned(), True)

    def test_a_tombstone_dir_also_counts_like_hermes_exists(self):
        (self.deleted / SENDER).mkdir(parents=True)
        self.assertIs(self.tombstoned(), True)

    def test_no_hermes_home_is_false(self):
        self.tombstone()
        self.assertIs(push_sender.tombstoned(self.cfg, {}), False)
        self.assertIs(push_sender.tombstoned(None, {"HERMES_HOME": str(self.hermes / "nope")}), False)

    def test_the_hermes_home_argument_is_used(self):
        self.tombstone()
        self.assertIs(push_sender.tombstoned(self.cfg, {}, self.hermes), True)

    def test_the_env_profile_and_the_owner_reply_pick_the_name(self):
        self.tombstone("relay")
        self.assertIs(push_sender.tombstoned(self.cfg, dict(self.env, KEVIN_PUSH_PROFILE="relay")), True)
        (self.st / push_sender.REPLY_FILE).write_text(json.dumps({"profile": "relay", "at": NOW}))
        self.assertIs(self.tombstoned(), True)

    def test_an_unreadable_deleted_dir_is_false(self):
        self.tombstone()
        real = Path.exists

        def exists(p, *a, **k):
            if p.parent.name == push_sender.DELETED_DIR:
                raise PermissionError("unreadable")
            return real(p, *a, **k)

        with mock.patch.object(Path, "exists", exists):
            self.assertIs(self.tombstoned(), False)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads any dir")
    def test_a_deleted_dir_without_permission_is_false_and_keeps_the_old_words(self):
        self.tombstone()
        os.chmod(self.deleted, 0)
        self.addCleanup(os.chmod, self.deleted, 0o755)
        self.assertIs(self.tombstoned(), False)
        self.assertEqual(self.row()["reason"], MISSING_ROW)
        self.assertEqual(self.reason(), MISSING_REASON)

    def test_it_never_opens_a_file_or_raises(self):
        self.tombstone()
        boom = mock.Mock(side_effect=AssertionError("a file was opened"))
        with mock.patch("builtins.open", boom), mock.patch("io.open", boom), \
                mock.patch.object(Path, "read_bytes", boom), mock.patch.object(Path, "read_text", boom):
            self.assertIs(push_sender.tombstoned({"push_profile": SENDER}, {"HERMES_HOME": str(self.hermes)}),
                          True)
        with mock.patch.object(push_sender, "profile", side_effect=RuntimeError("broken")):
            self.assertIs(self.tombstoned(), False)


class Words(Base):
    def test_the_doctor_row(self):
        self.tombstone()
        self.assertEqual(self.row(), {"name": "push sender", "kind": "source", "status": "missing",
                                      "reason": DELETED_ROW})

    def test_the_reason_wins_over_missing(self):
        self.tombstone()
        self.write_log(FAILING_LAST)
        self.assertEqual(push_reach.SENDER_DELETED, DELETED_REASON)
        self.assertEqual(push_reach.REASONS, (push_reach.SENDER_DELETED, push_reach.SENDER_MISSING,
                                              push_reach.SENDER_NO_BOT, push_reach.SEND_FAILING))
        self.assertEqual(self.reason(), DELETED_REASON)
        self.assertEqual(push_reach.line(self.reason()), PREFIX + DELETED_REASON)

    def test_the_hint_with_no_ready_profile(self):
        self.tombstone()
        self.write_log(FAILING_LAST)
        self.assertEqual(self.hint(), RESTORE)
        self.assertEqual(self.outage(), [PREFIX + DELETED_REASON + ". " + RESTORE])

    def test_the_hint_still_offers_a_ready_profile(self):
        self.tombstone()
        self.live("helper")
        self.write_log(FAILING_LAST)
        self.assertEqual(self.hint(), "Reply restore courier to bring it back or reply push via helper.")
        self.live("relay")
        self.assertEqual(self.hint(),
                         "Reply restore courier to bring it back or reply push via one of: helper, relay.")

    def test_the_recovery_words(self):
        self.tombstone()
        self.write_log(FAILING_LAST)
        self.assertEqual(self.stage(), ("missing", WAITING + DELETED_TAIL + "; no profile can reach Telegram"))
        self.live("helper")
        self.assertEqual(self.stage(), ("missing", WAITING + DELETED_TAIL + "; ready profiles: helper"))
        self.assertEqual(doctor.push_recovery_row(self.r, self.cfg, NOW, self.env)["reason"],
                         WAITING + DELETED_TAIL + "; ready profiles: helper")

    def test_status_and_packet_carry_the_reason(self):
        self.tombstone()
        self.write_log(FAILING_LAST)
        d = tools.status_with_delivery(self.r, NOW, self.cfg, self.env, TODAY)["delivery"]
        self.assertEqual(d, {"value": PREFIX + DELETED_REASON, "modality": "measured", "age_h": None,
                             "evidence_tier": "stale"})
        self.assertEqual(self.build()["items"]["delivery"]["value"], PREFIX + DELETED_REASON)
        p = context_packet.packet(self.st, NOW, TODAY, self.env)
        self.assertIn(PREFIX + DELETED_REASON, json.dumps(p))

    def test_no_digit_path_or_host_on_the_card(self):
        self.tombstone()
        self.live("helper")
        self.write_log(FAILING_LAST)
        c = self.build()
        line = self.outage(c["lines"])
        self.assertEqual(len(line), 1)
        self.assertEqual(re.findall(r"\d", c["text"]), [])
        self.assertNotIn(self.tmp.name, c["text"])
        self.assertNotIn("/", line[0])
        for words in (DELETED_ROW, DELETED_REASON, RESTORE, RESTORE_GENERIC, DELETED_TAIL, self.hint()):
            self.assertNotRegex(words, r"[\d/]")


class DigitName(Base):
    sender_name = "courier2"

    def test_a_name_with_a_digit_gets_the_generic_restore_words(self):
        self.tombstone()
        self.write_log(FAILING_LAST)
        self.assertIs(self.tombstoned(), True)
        self.assertEqual(self.hint(), RESTORE_GENERIC)
        self.live("helper")
        self.assertEqual(self.hint(), "Restore the deleted sender profile to bring it back or reply push via helper.")
        c = self.build()
        self.assertEqual(re.findall(r"\d", c["text"]), [])
        self.assertEqual(self.row()["reason"], DELETED_ROW)
        self.assertEqual(self.stage()[1], WAITING + DELETED_TAIL + "; ready profiles: helper")


class Unchanged(Base):
    """No tombstone (or a live dir beside it): every string is today's, byte for byte."""

    def check_old_words(self):
        self.write_log(FAILING_LAST)
        self.assertEqual(self.row()["reason"], MISSING_ROW)
        self.assertEqual(self.reason(), MISSING_REASON)
        self.assertEqual(self.hint(), GENERIC)
        self.assertEqual(self.stage(), ("missing", WAITING + "; no profile can reach Telegram"))
        self.assertEqual(self.outage(), [PREFIX + MISSING_REASON + ". " + GENERIC])

    def test_a_missing_sender_without_a_tombstone(self):
        self.check_old_words()

    def test_a_tombstone_for_another_profile(self):
        self.tombstone("relay")
        self.check_old_words()

    def test_a_live_sender_beside_its_tombstone(self):
        self.tombstone()
        self.live(SENDER, ready=True)
        self.write_log(FAILING_LAST)
        self.assertEqual(self.row(), {"name": "push sender", "kind": "source", "status": "live", "reason": "ready"})
        self.assertEqual(self.reason(), push_reach.SEND_FAILING)
        self.assertEqual(self.hint(), GENERIC)
        # candidates still skip a name with a tombstone (unchanged): only the wording rule is under test here
        self.assertEqual(self.stage(), ("missing", WAITING + "; no profile can reach Telegram"))

    def test_a_live_sender_keeps_the_ready_hint(self):
        self.live(SENDER, ready=False)
        self.live("helper")
        self.write_log(FAILING_LAST)
        self.assertEqual(self.hint(), "Reply push via helper to fix it.")
        self.assertEqual(self.row()["reason"], "no Telegram bot token in the sender profile")


class Cache(Base):
    def setUp(self):
        super().setUp()
        self.c = card.CardCache()

    def get(self):
        return self.c.get(self.r, NOW, TODAY, env=self.env)

    def test_a_new_tombstone_rebuilds_the_card(self):
        self.deleted.mkdir()
        self.write_log(FAILING_LAST)
        self.assertIn(PREFIX + MISSING_REASON + ". " + GENERIC, self.get())
        self.bump(self.profiles)       # settle: the profiles dir mtime is now fixed for the rest of the test
        self.get()
        builds = self.c.builds
        self.tombstone()
        st = self.profiles.stat()
        self.bump(self.deleted)
        os.utime(self.profiles, ns=(st.st_atime_ns, st.st_mtime_ns))   # only .deleted changed
        self.assertIn(PREFIX + DELETED_REASON + ". " + RESTORE, self.get())
        self.assertEqual(self.c.builds, builds + 1)

    def test_a_restore_rebuilds_the_card(self):
        self.tombstone()
        self.write_log(FAILING_LAST)
        self.assertIn(PREFIX + DELETED_REASON + ". " + RESTORE, self.get())
        builds = self.c.builds
        (self.deleted / SENDER).unlink()    # Hermes' restore: clear_named_profile_deleted + a live profile
        self.live(SENDER)
        self.bump(self.deleted)
        self.assertNotIn(DELETED_REASON, self.get())
        self.assertEqual(self.c.builds, builds + 1)

    def test_the_key_holds_the_deleted_dir_mtime(self):
        self.tombstone()
        k1 = push_reach.key(self.cfg, self.st, self.env)
        self.bump(self.deleted)
        self.assertNotEqual(push_reach.key(self.cfg, self.st, self.env), k1)


if __name__ == "__main__":
    unittest.main()
