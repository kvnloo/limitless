"""bin/limitless-brief end to end with a fake limitless_loop in a temp HOME. Synthetic data only."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-brief"

FAKE_LOOP = '''
import json, os
from pathlib import Path
def load_config():
    return {}
def build(cfg, day=None):
    return {"path": "/dev/null", "notif": "State: synthetic\\nDecision: ship t_deadbeef first"}
def deliver(cfg, title, body, url=None, env=None):
    Path(os.environ["HOME"], "delivered.txt").write_text(body)
    return {"rc": 0, "shown": "telegram"}
'''


class LimitlessBriefCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        lib = self.home / ".local/lib"
        lib.mkdir(parents=True)
        (lib / "limitless_loop.py").write_text(FAKE_LOOP)
        self.st = self.home / ".local/state/kevin-push"
        self.st.mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.home))

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(self.env),
                              capture_output=True, text=True, timeout=30)

    def test_send_adds_one_asks_line_and_no_card_ids(self):
        (self.st / "asks-latest.json").write_text(json.dumps(
            {"at": int(time.time()), "count": 3, "lines": ["A0001: Pick a color?", "A0002: Approve it?", "2 waiting"]}))
        r = self.run_cli("send")
        self.assertEqual(r.returncode, 0, r.stderr)
        body = (self.home / "delivered.txt").read_text()
        self.assertNotIn("t_deadbeef", body)
        self.assertEqual(body.splitlines()[-1], "Asks waiting on you: 2 (first: Pick a color?)")
        self.assertEqual(json.loads(r.stdout)["notify_rc"], 0)

    def test_send_without_asks_digest_still_delivers(self):
        r = self.run_cli("send")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.home / "delivered.txt").read_text(), "State: synthetic\nDecision: ship first")


if __name__ == "__main__":
    unittest.main()
