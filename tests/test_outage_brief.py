"""The outage line in the wake brief: jobs_runner.brief_outage / brief_outage_told, brief_post.finalize and
bin/limitless-brief end to end. It rides the brief through the tier audit gate; never a push of its own.

Synthetic inputs.json, a temp config and HOME, a fake limitless_loop; nothing real.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import brief_post, jobs_runner, outage  # noqa: E402

NOW = 1894708800.0
H = 3600.0
CLI = ROOT / "bin" / "limitless-brief"
HINT = "Open the app once to restart it."
FAKE_LOOP = '''
import json, os
from pathlib import Path
def load_config():
    return {}
def build(cfg, day=None):
    return {"path": "/dev/null", "notif": "State: synthetic"}
def deliver(cfg, title, body, url=None, env=None):
    if os.environ.get("FAKE_FAIL"):
        return {"rc": 1, "shown": "log"}
    with open(Path(os.environ["HOME"], "delivered.txt"), "a") as f:
        f.write(body + "\\n---\\n")
    return {"rc": 0, "shown": "telegram"}
'''


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg_path = self.root / "config.json"
        self.audit = self.root / "audit.jsonl"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg_path), "LIMITLESS_AUDIT": str(self.audit)}

    def config(self, cfg):
        self.cfg_path.write_text(json.dumps(cfg))

    def inputs(self, at, ages):
        (self.st / "inputs.json").write_text(json.dumps({"at": iso(at), "ageHours": ages}))


class BriefOutage(Case):
    def test_the_line_once_then_nothing_after_it_was_told(self):
        self.config({"outage_hints": {"wearable": HINT}})
        self.inputs(NOW, {"wearable": 50.0, "phone": 1.0})
        text = jobs_runner.brief_outage(self.st, NOW, self.env, self.root)
        self.assertEqual(text, "Not recording: wearable (since about two days ago). " + HINT)
        self.assertEqual(jobs_runner.brief_outage(self.st, NOW, self.env, self.root), text)   # not told yet
        self.assertTrue(jobs_runner.brief_outage_told(self.st, NOW, self.env, self.root))
        for k in range(1, 10):
            self.assertEqual(jobs_runner.brief_outage(self.st, NOW + k * H, self.env, self.root), "", k)

    def test_through_the_gate_hook_brief_outage(self):
        self.config({})
        self.inputs(NOW, {"wearable": 50.0})
        jobs_runner.brief_outage(self.st, NOW, self.env, self.root)
        row = json.loads(self.audit.read_text().splitlines()[-1])
        self.assertEqual((row["hook"], row["digits"], row["blocked"]), ("brief:outage", 0, False))

    def test_off_is_no_line_and_no_mark(self):
        self.config({"input_outage": False})
        self.inputs(NOW, {"wearable": 50.0})
        self.assertEqual(jobs_runner.brief_outage(self.st, NOW, self.env, self.root), "")
        self.assertFalse(jobs_runner.brief_outage_told(self.st, NOW, self.env, self.root))
        self.assertFalse((self.st / outage.MARK_FILE).exists())

    def test_preview_writes_nothing(self):
        self.config({})
        self.inputs(NOW, {"phone": "down"})
        self.assertNotEqual(jobs_runner.brief_outage(self.st, NOW, self.env, self.root, write=False), "")
        self.assertFalse((self.st / outage.MARK_FILE).exists())

    def test_unreadable_state_is_no_line(self):
        self.config({})
        self.assertEqual(jobs_runner.brief_outage(self.root / "nowhere", NOW, self.env, self.root), "")

    def test_finalize_adds_the_outage_line_last_only_when_given(self):
        line = "Not recording: wearable (since about two days ago)."
        self.assertEqual(brief_post.finalize("State: synthetic", None, NOW, naps="Naps yesterday: none",
                                             outage=line).splitlines()[-1], line)
        self.assertEqual(brief_post.finalize("State: synthetic", None, NOW, outage=""), "State: synthetic")


class Cli(unittest.TestCase):
    """bin/limitless-brief: send says the outage once (marked only after a real delivery); build only previews."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        lib = self.home / ".local/lib"
        lib.mkdir(parents=True)
        (lib / "limitless_loop.py").write_text(FAKE_LOOP)
        (self.home / ".local/state/kevin-push").mkdir(parents=True)
        self.st = self.home / ".local/state/limitless"
        self.st.mkdir(parents=True)
        (self.st / "inputs.json").write_text(json.dumps({"at": iso(time.time()), "ageHours": {"wearable": 50.0}}))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("LIMITLESS_", "KEVIN_PUSH"))}
        self.env["HOME"] = str(self.home)

    def run_cli(self, *args, **extra):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(dict(self.env, **extra)),
                              capture_output=True, text=True, timeout=60)

    def sent(self):
        p = self.home / "delivered.txt"
        return [b.strip() for b in p.read_text().split("---") if b.strip()] if p.exists() else []

    def test_send_says_it_once(self):
        for _ in range(3):
            r = self.run_cli("send")
            self.assertEqual(r.returncode, 0, r.stderr)
        got = self.sent()
        self.assertEqual(len(got), 3)
        self.assertEqual(got[0].splitlines()[-1], "Not recording: wearable (since about two days ago).")
        self.assertEqual(got[1], "State: synthetic")
        self.assertEqual(got[2], "State: synthetic")
        self.assertIsNone(re.search(r"\d", got[0]))

    def test_a_failed_send_keeps_it_for_the_next_brief(self):
        self.run_cli("send", FAKE_FAIL="1")
        self.run_cli("send")
        self.assertIn("Not recording: wearable", self.sent()[0])

    def test_build_previews_without_marking(self):
        r = self.run_cli("build")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Not recording: wearable", json.loads(r.stdout)["notif_text"])
        self.assertFalse((self.st / outage.MARK_FILE).exists())
        self.run_cli("send")
        self.assertIn("Not recording: wearable", self.sent()[0])


if __name__ == "__main__":
    unittest.main()
