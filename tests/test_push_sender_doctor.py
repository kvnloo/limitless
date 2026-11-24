"""limitless-doctor's "push sender" row: whether kevin-push's sender profile can exist, from files only, right
after the delivery row. Temp Hermes homes and state dirs; synthetic names only; no process is ever started."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import doctor  # noqa: E402

NOW = 1894708800.0  # 2030-01-15T12:00:00Z, the fixture clock


def no_process(*a, **k):
    raise AssertionError("the doctor started a process")


class NoProcess(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.hermes = self.home / "hermes"
        (self.hermes / "profiles").mkdir(parents=True)
        for target in ((subprocess, "Popen"), (os, "fork"), (os, "posix_spawn"), (os, "system")):
            if hasattr(*target):
                p = mock.patch.object(*target, side_effect=no_process)
                p.start()
                self.addCleanup(p.stop)


class Row(NoProcess):
    def row(self, cfg, **env):
        return doctor.push_sender_row(cfg, dict(env, HERMES_HOME=str(self.hermes)))

    def test_the_profile_exists_is_live(self):
        (self.hermes / "profiles" / "sender-a").mkdir()
        r = self.row({"push_profile": "sender-a"})
        self.assertEqual(r, {"name": "push sender", "kind": "source", "status": "live",
                             "reason": "set: the sender profile exists"})

    def test_the_profile_is_gone_is_missing_broken(self):
        r = self.row({"push_profile": "sender-a"})
        self.assertEqual((r["status"], r["reason"]), ("missing", "broken: the sender profile does not exist"))

    def test_an_unknown_home_is_missing_unknown(self):
        r = doctor.push_sender_row({"push_profile": "sender-a"}, {"HERMES_HOME": str(self.home / "nowhere")})
        self.assertEqual((r["status"], r["reason"]), ("missing", "unknown: the Hermes home does not exist"))

    def test_the_env_profile_wins_over_config(self):
        (self.hermes / "profiles" / "sender-a").mkdir()
        self.assertEqual(self.row({"push_profile": "sender-a"}, KEVIN_PUSH_PROFILE="sender-b")["status"], "missing")

    def test_strict_does_not_count_it(self):
        self.assertFalse(doctor.strict_failed([self.row({"push_profile": "sender-a"})]))


class InTheReport(NoProcess):
    def rows(self, cfg, **env):
        st = self.home / "state"
        st.mkdir(exist_ok=True)
        cfg = dict(cfg, state=str(st))
        cfg_path = self.home / "config.json"
        cfg_path.write_text(json.dumps(cfg))
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("LIMITLESS_", "KEVIN_PUSH_", "HERMES_"))}
        clean.update(env, HOME=str(self.home), LIMITLESS_CONFIG=str(cfg_path), HERMES_HOME=str(self.hermes))
        with mock.patch.dict(os.environ, clean, clear=True):
            return doctor.report(cfg, NOW)

    def test_right_after_the_delivery_row_and_before_the_sleep_mode_row(self):
        names = [r["name"] for r in self.rows({})]
        self.assertEqual(names[names.index("delivery") + 1], "push sender")
        self.assertEqual(names[names.index("push sender") + 1], "Sleep mode")
        self.assertEqual(names.count("push sender"), 1)

    def test_the_report_reads_the_same_config_and_env_kevin_push_does(self):
        (self.hermes / "profiles" / "sender-a").mkdir()
        got = {r["name"]: r for r in self.rows({"push_profile": "sender-a"})}["push sender"]
        self.assertEqual(got["status"], "live")
        got = {r["name"]: r for r in self.rows({"push_profile": "sender-a"}, KEVIN_PUSH_PROFILE="sender-b")}
        self.assertEqual(got["push sender"]["reason"], "broken: the sender profile does not exist")

    def test_no_name_target_or_path_in_text_or_json(self):
        rows = self.rows({"push_profile": "sender-zz", "push_to": "telegram:example-zz"})
        out = doctor.text(rows) + doctor.as_json(rows)
        for leak in ("sender-zz", "example-zz", str(self.hermes)):
            self.assertNotIn(leak, out)


class Docs(unittest.TestCase):
    def test_doctor_md_names_the_row_its_keys_and_its_words(self):
        text = (Path(__file__).resolve().parents[1] / "docs" / "doctor.md").read_text()
        for word in ("`push sender`, right after the delivery row", "push_profile", "KEVIN_PUSH_PROFILE",
                     "set: the sender profile exists", "broken: the sender profile does not exist", "unknown:",
                     "push sender: live: set: the sender profile exists"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
