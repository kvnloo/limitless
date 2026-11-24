"""bin/limitless-jobs --send end to end for the outage recap, with a fake kevin-push (never the real one) in a temp
HOME. Synthetic kevin-push log rows placed relative to the CLI's own clock; env passed explicitly."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-jobs"
H = 3600

# Records each call and, like the real one, appends its row to the push log (how from FAKE_PUSH_HOW).
FAKE_PUSH = """#!{py}
import json, os, sys, time
with open(os.environ["FAKE_PUSH_CALLS"], "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "strict": os.environ.get("KEVIN_PUSH_STRICT")}}) + "\\n")
how = os.environ.get("FAKE_PUSH_HOW", "telegram")
with open(os.environ["FAKE_PUSH_LOG"], "a") as f:
    f.write(json.dumps({{"at": int(time.time()), "tag": sys.argv[1], "cls": "decision", "title": sys.argv[2],
                        "body": sys.argv[3], "how": how}}) + "\\n")
print("kevin-push: " + how)
sys.exit(0 if how == "telegram" or os.environ.get("KEVIN_PUSH_STRICT") != "1" else 3)
"""


def row(at, title, how):
    return {"at": int(at), "tag": "limitless", "cls": "decision", "title": title, "how": how,
            "body": "Private body words.\nWhy now: a reason"}


class OutageRecapCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        bindir = self.home / "bin"
        bindir.mkdir()
        fake = bindir / "kevin-push"
        fake.write_text(FAKE_PUSH.format(py=sys.executable))
        fake.chmod(0o755)
        self.calls = self.home / "calls.jsonl"
        self.log = self.st / "push-log.jsonl"
        (self.home / "config.json").write_text(json.dumps({"outage_recap": "write", "push_log": "push-log.jsonl"}))
        self.env = {"HOME": str(self.home), "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
                    "LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.home / "config.json"),
                    "KEVIN_PUSH_BIN": str(fake), "FAKE_PUSH_CALLS": str(self.calls), "FAKE_PUSH_LOG": str(self.log)}

    def tearDown(self):
        self.tmp.cleanup()

    def write_log(self, rows):
        self.log.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def run_cli(self, *args, **env):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(dict(self.env, **env)),
                              capture_output=True, text=True, timeout=60)

    def calls_made(self):
        return [json.loads(ln) for ln in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def recap_line(self, out):
        return [ln for ln in out.splitlines() if ln.startswith("Outage recap: ")]

    def test_a_closed_outage_is_recapped_once_with_its_once_key(self):
        now = time.time()
        first = int(now - 5 * H)
        self.write_log([row(now - 6 * H, "Week review", "telegram"), row(first, "Wake-up brief", "log (telegram rc=1)"),
                        row(now - 4 * H, "MIQ for tonight?", "log (no sender profile)"),
                        row(now - 600, "Habit check-in", "telegram")])
        r = self.run_cli("--send")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.recap_line(r.stdout), ["Outage recap: deliver: pushes came back after an outage; sent"])
        calls = self.calls_made()
        self.assertEqual(len(calls), 1)
        argv = calls[0]["argv"]
        self.assertEqual(argv[:2], ["limitless", "Pushes are back"])
        self.assertEqual(argv[argv.index("--once") + 1], f"outage_recap:{first}")
        self.assertEqual(argv[argv.index("--why") + 1], "pushes are reaching you again after an outage")
        self.assertEqual(calls[0]["strict"], "1")
        body = argv[2]
        self.assertTrue(body.startswith("Phone pushes are reaching you again.\nMissed since"), body)
        self.assertIn("(wake brief, MIQ prompt)", body)
        self.assertTrue(body.endswith("Reply: OK / More"), body)
        self.assertIsNone(re.search(r"\d", body))
        self.assertNotIn("Private", body)
        # a repeat poll must not re-send
        r = self.run_cli("--send")
        self.assertEqual(self.recap_line(r.stdout), ["Outage recap: drop: already told about this outage"])
        self.assertEqual(len(self.calls_made()), 1)

    def test_an_open_outage_and_a_dry_run_send_nothing(self):
        now = time.time()
        self.write_log([row(now - 3 * H, "Wake-up brief", "log (telegram rc=1)"),
                        row(now - 2 * H, "Back from nap", "log (telegram rc=1)")])
        r = self.run_cli("--send")
        self.assertEqual(self.recap_line(r.stdout),
                         ["Outage recap: not_triggered: pushes are still failing; the state card already says so"])
        self.write_log([row(now - 3 * H, "Wake-up brief", "log (telegram rc=1)"),
                        row(now - 2 * H, "Back from nap", "log (telegram rc=1)"), row(now - 60, "x", "telegram")])
        r = self.run_cli()
        self.assertEqual(self.recap_line(r.stdout), ["Outage recap: deliver: pushes came back after an outage; would "
                                                     "send the recap (dry run of limitless-jobs): nothing sent"])
        self.assertEqual(self.calls_made(), [])
        self.assertFalse((self.st / "outage-recap.json").exists())

    def test_a_failed_recap_push_is_not_marked_told(self):
        now = time.time()
        self.write_log([row(now - 3 * H, "Wake-up brief", "log (telegram rc=1)"),
                        row(now - 2 * H, "Back from nap", "log (telegram rc=1)"), row(now - 60, "x", "telegram")])
        r = self.run_cli("--send", FAKE_PUSH_HOW="log (telegram rc=1)")
        self.assertEqual(self.recap_line(r.stdout), ["Outage recap: hold: pushes came back after an outage; not "
                                                     "delivered: log (telegram rc=1) (exit 3); the next run tries "
                                                     "again"])
        self.assertFalse((self.st / "outage-recap.json").exists())


if __name__ == "__main__":
    unittest.main()
