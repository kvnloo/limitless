"""limitless.push_sender: which Hermes profile and target kevin-push sends through, and whether that profile can
exist, decided from files only (no process, no send). Temp Hermes homes; synthetic names only."""
from hermetic_env import TEST_HOME  # first import: isolates HOME, see tests/hermetic_env.py
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import push_sender as ps  # noqa: E402

SET, BROKEN = "set: the sender profile exists", "broken: the sender profile does not exist"


def no_process(*a, **k):
    raise AssertionError("push_sender started a process")


class Resolve(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(ps.profile({}, {}), "intake")
        self.assertEqual(ps.target({}, {}), "telegram:kevin")

    def test_env_beats_config_beats_default(self):
        cfg = {"push_profile": "sender-a", "push_to": "telegram:example-a"}
        self.assertEqual((ps.profile(cfg, {}), ps.target(cfg, {})), ("sender-a", "telegram:example-a"))
        env = {"KEVIN_PUSH_PROFILE": "sender-b", "KEVIN_PUSH_TO": "telegram:example-b"}
        self.assertEqual((ps.profile(cfg, env), ps.target(cfg, env)), ("sender-b", "telegram:example-b"))

    def test_blank_and_non_string_values_are_skipped(self):
        env = {"KEVIN_PUSH_PROFILE": " "}
        self.assertEqual(ps.profile({"push_profile": "sender-a"}, env), "sender-a")
        self.assertEqual(ps.profile({"push_profile": 3}, {}), "intake")
        self.assertEqual(ps.profile(None, {}), "intake")
        self.assertEqual(ps.target(["x"], {}), "telegram:kevin")


class HermesRoot(unittest.TestCase):
    def test_unset_is_the_platform_default_under_home(self):
        self.assertEqual(ps.hermes_root({"HOME": "/x/h"}), Path("/x/h/.hermes"))

    def test_the_data_dir_suffix_is_kept(self):
        self.assertEqual(ps.hermes_root({"HOME": "/x/h", "HERMES_DATA_DIR_SUFFIX": "-dev"}), Path("/x/h/.hermes-dev"))

    def test_a_custom_root_is_itself(self):
        self.assertEqual(ps.hermes_root({"HERMES_HOME": "/srv/data"}), Path("/srv/data"))

    def test_a_profile_shaped_home_is_its_grandparent(self):
        self.assertEqual(ps.hermes_root({"HERMES_HOME": "/srv/data/profiles/other"}), Path("/srv/data"))

    def test_user_syntax_is_expanded(self):
        self.assertEqual(ps.hermes_root({"HERMES_HOME": "~/hh", "HOME": "/x/h"}), Path("/x/h/hh"))

    def test_no_home_at_all_is_none(self):
        self.assertIsNone(ps.hermes_root({}))


class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "hermes"
        (self.root / "profiles").mkdir(parents=True)
        patcher = mock.patch.object(subprocess, "Popen", side_effect=no_process)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_profile_dir_exists(self):
        (self.root / "profiles" / "sender-a").mkdir()
        self.assertEqual(ps.check({"push_profile": "sender-a"}, {}, self.root), SET)

    def test_the_profile_dir_is_missing(self):
        self.assertEqual(ps.check({"push_profile": "sender-a"}, {}, self.root), BROKEN)

    def test_the_default_profile_always_exists(self):
        self.assertEqual(ps.check({"push_profile": "default"}, {}, self.root), SET)
        self.assertEqual(ps.check({}, {"KEVIN_PUSH_PROFILE": "Default"}, self.root), SET)

    def test_the_built_in_default_profile_is_checked_too(self):
        self.assertEqual(ps.check({}, {}, self.root), BROKEN)
        (self.root / "profiles" / "intake").mkdir()
        self.assertEqual(ps.check({}, {}, self.root), SET)

    def test_the_name_is_matched_lowercase_as_hermes_stores_it(self):
        (self.root / "profiles" / "sender-a").mkdir()
        self.assertEqual(ps.check({"push_profile": "Sender-A"}, {}, self.root), SET)

    def test_env_profile_beats_config(self):
        (self.root / "profiles" / "sender-a").mkdir()
        self.assertEqual(ps.check({"push_profile": "sender-a"}, {"KEVIN_PUSH_PROFILE": "sender-b"}, self.root),
                         BROKEN)
        self.assertEqual(ps.check({"push_profile": "sender-b"}, {"KEVIN_PUSH_PROFILE": "sender-a"}, self.root), SET)

    def test_a_name_hermes_refuses_cannot_exist(self):
        (self.root / "x").mkdir()
        for bad in ("../x", "a/b", "-a", "a" * 65):
            self.assertEqual(ps.check({"push_profile": bad}, {}, self.root), BROKEN, bad)

    def test_a_file_where_the_dir_should_be_is_broken(self):
        (self.root / "profiles" / "sender-a").write_text("")
        self.assertEqual(ps.check({"push_profile": "sender-a"}, {}, self.root), BROKEN)

    def test_the_home_from_hermes_home_when_none_is_passed(self):
        (self.root / "profiles" / "sender-a").mkdir()
        env = {"HERMES_HOME": str(self.root / "profiles" / "other")}
        self.assertEqual(ps.check({"push_profile": "sender-a"}, env), SET)
        self.assertEqual(ps.check({"push_profile": "sender-b"}, env), BROKEN)

    def test_a_missing_hermes_home_is_unknown(self):
        got = ps.check({"push_profile": "sender-a"}, {}, self.root.parent / "nowhere")
        self.assertEqual(got, "unknown: the Hermes home does not exist")

    def test_no_hermes_home_at_all_is_unknown(self):
        self.assertEqual(ps.check({}, {}), "unknown: no Hermes home is set (HERMES_HOME or HOME)")

    def test_an_unreadable_home_is_unknown(self):
        with mock.patch.object(Path, "is_dir", side_effect=PermissionError("no")):
            self.assertEqual(ps.check({}, {}, self.root), "unknown: the Hermes home cannot be read")

    def test_the_words_never_hold_the_profile_target_or_a_path(self):
        cfg = {"push_profile": "sender-zz", "push_to": "telegram:example-zz"}
        for home in (self.root, self.root.parent / "nowhere", None):
            got = ps.check(cfg, {"HERMES_HOME": str(self.root)} if home is None else {}, home)
            for leak in ("sender-zz", "example-zz", str(self.root), "/", str(TEST_HOME)):
                self.assertNotIn(leak, got)
            self.assertFalse(any(c.isdigit() for c in got))


if __name__ == "__main__":
    unittest.main()
