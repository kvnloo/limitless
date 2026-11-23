"""bin/limitless-jobs end to end with a fake kevin-push in a temp HOME. Synthetic data only.

The state is a nap (a short Sleep-mode on, then off): limitless-jobs pushes "Back from nap" itself; the
wake brief has its own sender (tests/test_job_owners_cli.py)."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-jobs"
H = 3600.0

FAKE_PUSH = """#!{py}
import json, os, sys
from pathlib import Path
with open(os.environ["FAKE_PUSH_CALLS"], "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "strict": os.environ.get("KEVIN_PUSH_STRICT"),
                        "cls": os.environ.get("CIRCADIAN_CLASS")}}) + "\\n")
how = os.environ.get("FAKE_PUSH_HOW", "telegram")
print("kevin-push: " + how)
sys.exit(0 if how == "telegram" or os.environ.get("KEVIN_PUSH_STRICT") != "1" else 3)
"""


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class LimitlessJobsCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        now = time.time()
        # ISO strings, as the phone sync writes them (bin/kevin-push reads the poll's "at" as a string).
        write_rows(self.st / "sleepmode.jsonl", [{"at": iso(now - 12 * H), "on": True}, {"at": iso(now - 3 * H), "on": False},
                                                 {"at": iso(now - 1 * H), "on": True}, {"at": iso(now - 0.1 * H), "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": iso(now - 30), "ok": True}))
        write_rows(self.st / "unlocks.jsonl", [{"at": iso(now - 60)}])
        bindir = self.home / "bin"
        bindir.mkdir()
        self.fake = bindir / "kevin-push"
        self.fake.write_text(FAKE_PUSH.format(py=sys.executable))
        self.fake.chmod(0o755)
        self.calls = self.home / "calls.jsonl"
        self.env = {"HOME": str(self.home), "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
                    "LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.home / "no-config.json"),
                    "FAKE_PUSH_CALLS": str(self.calls)}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, **env):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=dict(self.env, **env),
                              capture_output=True, text=True, timeout=30)

    def push_calls(self):
        return [json.loads(ln) for ln in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def sent(self):
        p = self.st / "jobs-sent.jsonl"
        return p.read_text().splitlines() if p.exists() else []

    def test_dry_run_by_default_one_line_per_job(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 5, r.stdout)   # five jobs, one line each
        self.assertTrue(any(ln.startswith("Back from nap: deliver") for ln in lines), r.stdout)
        self.assertEqual(self.push_calls(), [])
        self.assertEqual(self.sent(), [])

    def test_send_calls_kevin_push_strict_and_logs_once(self):
        r = self.run_cli("--send")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.push_calls()
        self.assertEqual(len(calls), 1, r.stdout)
        self.assertEqual(calls[0]["argv"][:2], ["limitless", "Back from nap"])
        self.assertEqual(calls[0]["strict"], "1")
        self.assertEqual(calls[0]["cls"], "decision")
        self.assertEqual(len(self.sent()), 1)
        r2 = self.run_cli("--send")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual(len(self.push_calls()), 1, r2.stdout)
        self.assertIn("Back from nap: drop", r2.stdout)

    def test_log_only_kevin_push_is_not_sent(self):
        r = self.run_cli("--send", FAKE_PUSH_HOW="log (daily cap)")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.push_calls()), 1)
        self.assertEqual(self.sent(), [])
        self.assertIn("Back from nap: hold", r.stdout)
        self.assertIn("not delivered", r.stdout)

    def test_kevin_push_bin_from_env(self):
        other = self.home / "other-push"
        other.write_text(self.fake.read_text())
        other.chmod(0o755)
        self.fake.unlink()
        r = self.run_cli("--send", KEVIN_PUSH_BIN=str(other))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.push_calls()), 1)
        self.assertEqual(len(self.sent()), 1)

    def test_missing_kevin_push_is_not_sent(self):
        r = self.run_cli("--send", KEVIN_PUSH_BIN=str(self.home / "nope"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.sent(), [])
        self.assertIn("not delivered", r.stdout)


    def real_kevin_push(self, hermes_rc):
        """The repo's own bin/kevin-push, with a fake `hermes` on PATH that exits hermes_rc."""
        hermes = self.home / "bin" / "hermes"
        hermes.write_text(f"#!/bin/sh\necho called >> '{self.home}/hermes-calls'\nexit {hermes_rc}\n")
        hermes.chmod(0o755)
        self.fake.unlink(missing_ok=True)
        return {"KEVIN_PUSH_BIN": str(ROOT / "bin" / "kevin-push")}

    def test_with_the_real_kevin_push_delivered(self):
        r = self.run_cli("--send", **self.real_kevin_push(0))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.sent()), 1, r.stdout)
        self.assertEqual((self.home / "hermes-calls").read_text().count("called"), 1)
        self.run_cli("--send", **self.real_kevin_push(0))
        self.assertEqual((self.home / "hermes-calls").read_text().count("called"), 1)

    def test_with_the_real_kevin_push_failed_telegram_is_not_sent(self):
        r = self.run_cli("--send", **self.real_kevin_push(1))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.sent(), [])
        self.assertIn("telegram rc=1", r.stdout)


if __name__ == "__main__":
    unittest.main()
