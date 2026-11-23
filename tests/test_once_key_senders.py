"""End to end: a shell sender using bin/limitless-once-key and bin/limitless-jobs --send, one MIQ per event.

Both go through the real bin/kevin-push with a temp HOME and a fake `hermes` on PATH, so nothing
really sends. The shell sender is the line docs/limitless-jobs-systemd.md shows. Synthetic data only.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import send_gate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / "bin" / "limitless-jobs"
KEVIN_PUSH = ROOT / "bin" / "kevin-push"
SHELL_SENDER = ('KEVIN_PUSH_ONCE=$(bin/limitless-once-key miq) '
                'kevin-push limitless "MIQ for tonight?" "Wind-down: pick the one thing for tomorrow."')


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ShellAndRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        bindir = self.home / "bin"
        bindir.mkdir()
        hermes = bindir / "hermes"
        hermes.write_text("#!/bin/sh\necho called >> \"$HOME/hermes-calls\"\nexit 0\n")
        hermes.chmod(0o755)
        kp = bindir / "kevin-push"                     # the real kevin-push, as the shell finds it on PATH
        kp.write_text(f"#!/bin/sh\nexec \"{sys.executable}\" -I \"{KEVIN_PUSH}\" \"$@\"\n")
        kp.chmod(0o755)
        self.att = self.home / "attention.json"
        self.env = {"HOME": str(self.home), "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
                    "LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.home / "no-config.json"),
                    "LIMITLESS_SLEEPMODE": str(self.st / "sleepmode.jsonl"), "KEVIN_PUSH_BIN": str(kp),
                    "LIMITLESS_GLIDE_ATTENTION": str(self.att), "CIRCADIAN_CLASS": "decision", "TZ": "UTC"}

    def tearDown(self):
        self.tmp.cleanup()

    def wind_down(self):
        at = int(time.time() - 120)
        wake = at - 4 * 3600   # the night date is the wake's (UTC) date; the wake brief is stale by now
        write_rows(self.st / "events.jsonl", [{"event": "wake", "at": iso(wake)}, {"event": "wind_down", "at": iso(at)}])
        self.att.write_text(json.dumps({"block": None, "resume": {"saved": at - 30}}))
        return f"miq:{datetime.fromtimestamp(wake, timezone.utc).date().isoformat()}"

    def shell_sender(self, line=SHELL_SENDER):
        return subprocess.run(["sh", "-c", line], cwd=ROOT, env=self.env, capture_output=True, text=True, timeout=60)

    def jobs_cli(self):
        return subprocess.run([sys.executable, "-I", str(JOBS), "--send"], env=self.env,
                              capture_output=True, text=True, timeout=60)

    def deliveries(self):
        p = self.home / "hermes-calls"
        return p.read_text().count("called") if p.exists() else 0

    def claimed(self):
        p = self.home / ".local/state/kevin-push/sent.json"
        return [r.get("once") for r in json.loads(p.read_text())] if p.exists() else []

    def test_shell_sender_first_then_runner_is_one_delivery(self):
        key = self.wind_down()
        s = self.shell_sender()
        self.assertEqual(s.stdout.strip(), "kevin-push: telegram", s.stderr)
        r = self.jobs_cli()
        self.assertIn("MIQ for tonight?: drop", r.stdout)
        self.assertIn(send_gate.ONCE_DROP, r.stdout)
        self.assertEqual(self.deliveries(), 1, r.stdout)
        self.assertEqual(self.claimed(), [key])

    def test_runner_first_then_shell_sender_is_one_delivery(self):
        key = self.wind_down()
        r = self.jobs_cli()
        self.assertIn("MIQ for tonight?: deliver", r.stdout)
        s = self.shell_sender()
        self.assertEqual(s.stdout.strip(), f"kevin-push: log ({send_gate.ONCE_DROP})", s.stderr)
        self.assertEqual(self.deliveries(), 1)
        self.assertEqual(self.claimed(), [key])

    def test_no_key_shell_sender_sends_as_before(self):
        k = subprocess.run(["sh", "-c", "bin/limitless-once-key miq"], cwd=ROOT, env=self.env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual((k.returncode, k.stdout), (3, ""))
        s = self.shell_sender()
        self.assertEqual(s.stdout.strip(), "kevin-push: telegram", s.stderr)
        self.assertEqual(self.deliveries(), 1)
        self.assertEqual(self.claimed(), [None])
        self.assertIn("MIQ for tonight?: not_triggered", self.jobs_cli().stdout)
        self.assertEqual(self.deliveries(), 1)

    def test_no_key_under_set_e_still_sends(self):
        s = self.shell_sender("set -e; " + SHELL_SENDER)
        self.assertEqual((s.returncode, s.stdout.strip()), (0, "kevin-push: telegram"), s.stderr)
        self.assertEqual(self.claimed(), [None])


if __name__ == "__main__":
    unittest.main()
