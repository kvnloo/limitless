"""A sender profile is live only the way Hermes decides it: push_sender.is_live and its use in check, readiness,
candidates and tombstoned.

Mirrors NousResearch/hermes-agent hermes_constants.py ``named_profile_is_live``: the dir exists, it has an identity
marker (``named_profile_has_identity`` over ``_PROFILE_IDENTITY_MARKERS``: a regular file or a symlink named
config.yaml, .env, SOUL.md, profile.yaml, auth.json or state.db) and no tombstone (``named_profile_is_deleted``:
``profile_tombstone_path`` = ``profiles/.deleted/<name>`` exists). hermes_cli/profiles.py ``resolve_profile_env``
(the ``-p`` path) refuses any profile that is not live.

Synthetic Hermes homes in a temp dir, made-up profile names (courier, helper, relay), a made-up token, env passed
explicitly. Nothing is run or sent and no process is started; no file is opened by is_live or check.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import doctor, push_sender  # noqa: E402

MARKERS = ("config.yaml", ".env", "SOUL.md", "profile.yaml", "auth.json", "state.db")
READY_ENV = "TELEGRAM_BOT_TOKEN=made-up-token\nTELEGRAM_HOME_CHANNEL=made-up-chat\n"
MISSING_ROW = "the sender profile does not exist"
DELETED_ROW = "the sender profile was deleted; restoring it should bring pushes back"


def no_process(*a, **k):
    raise AssertionError("a process was started")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "hermes"
        self.profiles = self.root / "profiles"
        self.profiles.mkdir(parents=True)
        self.env = {"HOME": self.tmp.name, "HERMES_HOME": str(self.root)}
        self.cfg = {"push_profile": "courier", "push_to": "telegram"}
        for target in ((subprocess, "Popen"), (os, "fork"), (os, "posix_spawn"), (os, "system")):
            if hasattr(*target):
                p = mock.patch.object(*target, side_effect=no_process)
                p.start()
                self.addCleanup(p.stop)

    def dir(self, name="courier"):
        p = self.profiles / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ghost(self, name="courier"):
        # what cron heartbeats and log rotation leave behind: dirs and files, but no identity marker
        p = self.dir(name)
        (p / "logs").mkdir(exist_ok=True)
        (p / "cron").mkdir(exist_ok=True)
        (p / "notes.txt").write_text("made-up\n")
        return p

    def ready(self, name="courier"):
        p = self.dir(name)
        (p / ".env").write_text(READY_ENV)
        return p

    def tombstone(self, name="courier"):
        # hermes_constants.mark_named_profile_deleted: a marker FILE profiles/.deleted/<name> holding "deleted\n"
        (self.profiles / ".deleted").mkdir(exist_ok=True)
        (self.profiles / ".deleted" / name).write_bytes(b"deleted\n")

    def live(self, name="courier"):
        return push_sender.is_live(self.root, name)


class IsLive(Base):
    def test_each_identity_marker_alone_makes_a_dir_live(self):
        for marker in MARKERS:
            with self.subTest(marker=marker):
                p = self.dir("helper-" + marker.strip(".").replace(".", "-").lower())
                (p / marker).write_text("made-up\n")
                self.assertIs(push_sender.is_live(self.root, p.name), True)

    def test_the_markers_are_hermes_own(self):
        self.assertEqual(push_sender.IDENTITY_MARKERS, MARKERS)

    def test_an_empty_marker_counts_like_hermes(self):
        # named_profile_has_identity only asks is_file()/is_symlink(); an empty .env (what a crashed
        # `hermes profile create` leaves) is enough for -p. Only named_profile_has_servable_identity, which -p
        # never asks, wants a non-empty .env.
        for marker in (".env", "config.yaml"):
            with self.subTest(marker=marker):
                p = self.dir("empty-" + marker.strip(".").replace(".", "-"))
                (p / marker).write_bytes(b"")
                self.assertIs(push_sender.is_live(self.root, p.name), True)

    def test_a_symlinked_marker_counts_even_dangling(self):
        p = self.dir()
        try:
            os.symlink(str(Path(self.tmp.name) / "nowhere"), str(p / "config.yaml"))
        except (OSError, NotImplementedError):
            self.skipTest("no symlinks here")
        self.assertIs(self.live(), True)

    def test_a_marker_that_is_a_dir_does_not(self):
        p = self.dir()
        for marker in MARKERS:
            (p / marker).mkdir()
        self.assertIs(self.live(), False)

    def test_a_ghost_dir_is_not_live(self):
        self.ghost()
        self.assertIs(self.live(), False)
        self.dir("relay")
        self.assertIs(self.live("relay"), False)

    def test_a_tombstone_beside_the_dir_wins(self):
        self.ready()
        self.assertIs(self.live(), True)
        self.tombstone()
        self.assertIs(self.live(), False)

    def test_a_tombstone_dir_counts_like_exists(self):
        self.ready()
        (self.profiles / ".deleted" / "courier").mkdir(parents=True)
        self.assertIs(self.live(), False)

    def test_another_profiles_tombstone_says_nothing(self):
        self.ready()
        self.tombstone("relay")
        self.assertIs(self.live(), True)

    def test_a_missing_dir_or_a_file_in_its_place_is_not_live(self):
        self.assertIs(self.live(), False)
        (self.profiles / "courier").write_text("made-up\n")
        self.assertIs(self.live(), False)

    def test_default_is_always_live(self):
        for name in ("default", "Default", " DEFAULT "):
            with self.subTest(name=name):
                self.assertIs(push_sender.is_live(self.root, name), True)
                self.assertIs(push_sender.is_live(None, name), True)
                self.assertIs(push_sender.is_live(self.root / "nope", name), True)

    def test_the_name_is_normalized_like_hermes(self):
        self.ready()
        self.assertIs(self.live(" Courier "), True)

    def test_names_hermes_never_resolves_are_not_live(self):
        self.ready()
        for name in ("", " ", "../courier", "profiles/courier", ".deleted", "-x", "a" * 65, None, 3):
            with self.subTest(name=name):
                self.assertIs(push_sender.is_live(self.root, name), False)

    def test_no_or_a_bad_root_is_false_and_never_raises(self):
        self.ready()
        self.assertIs(push_sender.is_live(None, "courier"), False)
        self.assertIs(push_sender.is_live(self.root / "nope", "courier"), False)
        self.assertIs(push_sender.is_live(object(), "courier"), False)
        self.assertIs(push_sender.is_live(str(self.root), "courier"), True)

    def test_anything_unreadable_is_false(self):
        self.ready()
        with mock.patch.object(push_sender.os, "lstat", side_effect=PermissionError("unreadable")), \
                mock.patch.object(push_sender.os, "stat", side_effect=PermissionError("unreadable")):
            self.assertIs(self.live(), False)

    def test_nothing_is_opened(self):
        self.ready()
        self.tombstone("relay")
        env = dict(self.env, KEVIN_PUSH_PROFILE="courier")   # the sender from env: the owner's reply file is not read
        boom = mock.Mock(side_effect=AssertionError("a file was opened"))

        def no_open():
            return (mock.patch("builtins.open", boom), mock.patch("io.open", boom), mock.patch("os.open", boom),
                    mock.patch.object(Path, "read_bytes", boom), mock.patch.object(Path, "read_text", boom),
                    mock.patch.object(Path, "open", boom))

        def run(expect_live):
            patches = no_open()
            for p in patches:
                p.start()
            try:
                self.assertIs(self.live(), expect_live)
                self.assertEqual(push_sender.check(self.cfg, env),
                                 push_sender.SET if expect_live else push_sender.BROKEN)
                self.assertIs(push_sender.tombstoned(self.cfg, env), not expect_live)
            finally:
                for p in reversed(patches):
                    p.stop()

        run(True)
        self.tombstone()
        run(False)
        boom.assert_not_called()


class Check(Base):
    def test_a_live_sender_is_set(self):
        self.ready()
        self.assertEqual(push_sender.check(self.cfg, self.env), push_sender.SET)

    def test_a_ghost_dir_is_broken_with_the_missing_words(self):
        self.ghost()
        self.assertEqual(push_sender.check(self.cfg, self.env), push_sender.BROKEN)
        self.assertEqual(push_sender.readiness(self.cfg, self.env), push_sender.MISSING)
        self.assertIs(push_sender.tombstoned(self.cfg, self.env), False)
        row = doctor.push_sender_row(self.cfg, self.env)
        self.assertEqual((row["status"], row["reason"]), ("missing", MISSING_ROW))

    def test_a_dir_beside_its_tombstone_is_broken_and_tombstoned(self):
        self.ready()
        self.tombstone()
        self.assertEqual(push_sender.check(self.cfg, self.env), push_sender.BROKEN)
        self.assertEqual(push_sender.readiness(self.cfg, self.env), push_sender.MISSING)
        self.assertIs(push_sender.tombstoned(self.cfg, self.env), True)
        row = doctor.push_sender_row(self.cfg, self.env)
        self.assertEqual((row["status"], row["reason"]), ("missing", DELETED_ROW))

    def test_a_ghost_beside_its_tombstone_is_tombstoned_too(self):
        self.ghost()
        self.tombstone()
        self.assertEqual(push_sender.check(self.cfg, self.env), push_sender.BROKEN)
        self.assertIs(push_sender.tombstoned(self.cfg, self.env), True)

    def test_a_marker_probe_that_cannot_be_read_is_unknown_not_broken(self):
        # kevin-push refuses a send on BROKEN only; an unreadable profile dir must not block it
        self.ready()
        real = os.lstat

        def lstat(p, *a, **k):
            if os.path.basename(str(p)) in MARKERS:
                raise PermissionError("unreadable")
            return real(p, *a, **k)

        with mock.patch.object(push_sender.os, "lstat", lstat):
            self.assertEqual(push_sender.check(self.cfg, self.env), push_sender.HOME_UNREADABLE)

    def test_default_is_still_set_without_a_home(self):
        self.assertEqual(push_sender.check({"push_profile": "default"}, {}), push_sender.SET)


class Candidates(Base):
    def test_ghost_and_tombstoned_dirs_are_skipped(self):
        self.ready("helper")
        self.ghost("relay")
        self.ready("courier")
        self.tombstone("courier")
        self.dir("bare")
        (self.dir("thin") / ".env").write_bytes(b"")   # live for Hermes; no token, so not ready
        got = push_sender.candidates(self.cfg, self.env)
        self.assertEqual([n for n, _ in got], ["default", "helper", "thin"])
        self.assertEqual(dict(got)["helper"], push_sender.READY)
        self.assertEqual(dict(got)["thin"], push_sender.NO_TOKEN)

    def test_a_dir_whose_markers_cannot_be_read_is_skipped(self):
        self.ready("helper")
        self.ready("relay")
        real = os.lstat

        def lstat(p, *a, **k):
            if os.path.basename(os.path.dirname(str(p))) == "relay":
                raise PermissionError("unreadable")
            return real(p, *a, **k)

        with mock.patch.object(push_sender.os, "lstat", lstat):
            got = push_sender.candidates(self.cfg, self.env)
        self.assertEqual([n for n, _ in got], ["default", "helper"])


if __name__ == "__main__":
    unittest.main()
