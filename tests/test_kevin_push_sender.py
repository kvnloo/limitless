"""bin/kevin-push's sender profile and target: env var > config key (push_profile, push_to) > the defaults.

A fake `hermes` on PATH records the argv it was started with; nothing is sent. Synthetic names only.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "kevin-push"


class KevinPushSender(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        fakebin = self.home / "fakebin"
        fakebin.mkdir()
        hermes = fakebin / "hermes"
        hermes.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$HOME/argv.txt\"\nexit 0\n")
        hermes.chmod(hermes.stat().st_mode | stat.S_IEXEC)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("KEVIN_PUSH_")}
        self.env.update(HOME=str(self.home), PATH=f"{fakebin}:{os.environ['PATH']}",
                        LIMITLESS_SLEEPMODE=str(self.home / "none.jsonl"), CIRCADIAN_CLASS="decision")

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, **cfg):
        path = self.home / ".config/limitless/config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cfg))

    def argv(self, **env):
        r = subprocess.run([sys.executable, "-I", str(CLI), "x", "Pick one", "Decision: keep the loop"],
                           env=child_env(self.env, **env), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("kevin-push: telegram", r.stdout)
        got = (self.home / "argv.txt").read_text().splitlines()
        return got[got.index("-p") + 1], got[got.index("--to") + 1], got

    def test_neither_set_keeps_the_current_defaults(self):
        profile, to, argv = self.argv()
        self.assertEqual((profile, to), ("intake", "telegram:kevin"))
        self.assertEqual(argv[:5], ["-p", "intake", "send", "--to", "telegram:kevin"])

    def test_config_keys_name_the_profile_and_target(self):
        self.config(push_profile="sender-a", push_to="telegram:example-a")
        self.assertEqual(self.argv()[:2], ("sender-a", "telegram:example-a"))

    def test_env_vars_win_over_the_config_keys(self):
        self.config(push_profile="sender-a", push_to="telegram:example-a")
        self.assertEqual(self.argv(KEVIN_PUSH_PROFILE="sender-b", KEVIN_PUSH_TO="telegram:example-b")[:2],
                         ("sender-b", "telegram:example-b"))

    def test_each_key_falls_back_on_its_own(self):
        self.config(push_to="telegram:example-a")
        self.assertEqual(self.argv(KEVIN_PUSH_PROFILE="sender-b")[:2], ("sender-b", "telegram:example-a"))

    def test_empty_or_non_string_config_values_are_the_defaults(self):
        self.config(push_profile="  ", push_to=7)
        self.assertEqual(self.argv()[:2], ("intake", "telegram:kevin"))

    def test_an_empty_env_var_falls_back_to_the_config_key(self):
        self.config(push_profile="sender-a")
        self.assertEqual(self.argv(KEVIN_PUSH_PROFILE="")[0], "sender-a")


if __name__ == "__main__":
    unittest.main()
