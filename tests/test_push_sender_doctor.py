"""limitless-doctor's "push sender" row: whether kevin-push's sender profile can reach Telegram
(push_sender.readiness), from files only, right after the delivery row. Temp Hermes homes and state dirs; synthetic
names and a made-up token only; no process is ever started."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import re
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
TOKEN = "SYNTHETICTOKENzz-doctor"   # made up; must never appear in the report
READY_ENV = f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_HOME_CHANNEL=12345\n"


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

    def sender(self, name, env_text=READY_ENV):
        home = self.hermes / "profiles" / name
        home.mkdir(parents=True)
        (home / ".env").write_text(env_text)


class Row(NoProcess):
    def row(self, cfg, **env):
        return doctor.push_sender_row(cfg, dict(env, HERMES_HOME=str(self.hermes)))

    def test_a_ready_profile_is_live(self):
        self.sender("sender-a")
        r = self.row({"push_profile": "sender-a", "push_to": "telegram"})
        self.assertEqual(r, {"name": "push sender", "kind": "source", "status": "live", "reason": "ready"})

    def test_the_profile_is_gone_is_missing(self):
        r = self.row({"push_profile": "sender-a"})
        self.assertEqual((r["status"], r["reason"]), ("missing", "missing: the sender profile does not exist"))

    def test_a_profile_without_a_token_is_missing_with_why(self):
        self.sender("sender-a", "TELEGRAM_HOME_CHANNEL=12345\n")
        r = self.row({"push_profile": "sender-a", "push_to": "telegram"})
        self.assertEqual((r["status"], r["reason"]), ("missing", "no Telegram bot token in the sender profile"))

    def test_a_profile_without_a_chat_is_missing_with_why(self):
        self.sender("sender-a", f"TELEGRAM_BOT_TOKEN={TOKEN}\n")
        r = self.row({"push_profile": "sender-a", "push_to": "telegram"})
        self.assertEqual((r["status"], r["reason"]), ("missing", "no Telegram chat set for the sender profile"))

    def test_an_unknown_home_is_missing_unknown(self):
        r = doctor.push_sender_row({"push_profile": "sender-a"}, {"HERMES_HOME": str(self.home / "nowhere")})
        self.assertEqual((r["status"], r["reason"]), ("missing", "unknown: the Hermes home does not exist"))

    def test_the_env_profile_wins_over_config(self):
        self.sender("sender-a")
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

    def test_right_after_the_delivery_row_and_before_the_sender_candidates_row(self):
        names = [r["name"] for r in self.rows({})]
        self.assertEqual(names[names.index("delivery") + 1], "push sender")
        self.assertEqual(names[names.index("push sender") + 1], "sender candidates")
        self.assertEqual(names[names.index("sender candidates") + 1], "push recovery")
        self.assertEqual(names.count("push sender"), 1)

    def test_the_report_reads_the_same_config_and_env_kevin_push_does(self):
        self.sender("sender-a")
        got = {r["name"]: r for r in self.rows({"push_profile": "sender-a", "push_to": "telegram"})}["push sender"]
        self.assertEqual((got["status"], got["reason"]), ("live", "ready"))
        got = {r["name"]: r for r in self.rows({"push_profile": "sender-a"}, KEVIN_PUSH_PROFILE="sender-b")}
        self.assertEqual(got["push sender"]["reason"], "missing: the sender profile does not exist")
        got = {r["name"]: r for r in self.rows({"push_profile": "sender-a", "push_to": "telegram"},
                                                KEVIN_PUSH_TO="telegram:example-zz")}
        self.assertEqual(got["push sender"]["reason"], "no Telegram chat set for the sender profile")

    def test_no_token_name_target_or_path_in_text_or_json(self):
        for env_text in (READY_ENV, f"TELEGRAM_BOT_TOKEN={TOKEN}\n"):
            home = self.hermes / "profiles" / "sender-zz"
            home.mkdir(parents=True, exist_ok=True)
            (home / ".env").write_text(env_text)
            for to in ("telegram", "telegram:example-zz"):
                rows = self.rows({"push_profile": "sender-zz", "push_to": to}, TELEGRAM_BOT_TOKEN=TOKEN + "-env")
                out = doctor.text(rows) + doctor.as_json(rows)
                for leak in (TOKEN, "SYNTHETICTOKEN", "example-zz", str(self.hermes)):
                    self.assertNotIn(leak, out)
                # the profile name only in the "sender candidates" row (the owner's own labels), never elsewhere
                named = [r for r in rows if r["name"] != doctor.SENDER_CANDIDATES_ROW]
                self.assertNotIn("sender-zz", doctor.text(named) + doctor.as_json(named))


class Docs(unittest.TestCase):
    def test_the_readiness_example_is_the_scripts_real_output(self):
        root = Path(__file__).resolve().parents[1]
        r = subprocess.run([sys.executable, "-I", str(root / "scripts" / "push_sender_readiness_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        for words in ("push sender: live: ready", "no Telegram bot token in the sender profile",
                      "no Telegram chat set for the sender profile", "missing: the sender profile does not exist"):
            self.assertIn(words, r.stdout)
        self.assertNotIn("made-up-token", r.stdout)
        blocks = re.findall(r"```text\n(.*?)```", (root / "docs" / "doctor.md").read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_doctor_md_names_the_row_its_keys_and_its_words(self):
        text = (Path(__file__).resolve().parents[1] / "docs" / "doctor.md").read_text()
        for word in ("`push sender`, right after the delivery row", "push_profile", "KEVIN_PUSH_PROFILE",
                     "TELEGRAM_BOT_TOKEN", "TELEGRAM_HOME_CHANNEL", "channel_directory.json", "ready",
                     "no Telegram bot token in the sender profile", "no Telegram chat set for the sender profile",
                     "missing: the sender profile does not exist", "unknown:", "report-only",
                     "push sender: live: ready"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
