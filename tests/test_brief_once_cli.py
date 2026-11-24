"""End to end: the wake brief's two senders (bin/limitless-brief and bin/limitless-jobs) share one event key.

Synthetic data only.
Nothing really sends: pushes are fakes, and the CLI tests put a fake `hermes` on PATH.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
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
BRIEF = ROOT / "bin" / "limitless-brief"
JOBS = ROOT / "bin" / "limitless-jobs"
KEVIN_PUSH = ROOT / "bin" / "kevin-push"
H = 3600.0


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


FAKE_LOOP = '''
import os, subprocess
from pathlib import Path
def load_config():
    return {}
def build(cfg, day=None):
    d = Path(os.environ["HOME"], "brief-day.txt")
    n = d.read_text().strip() if d.exists() else "1"
    return {"path": "/dev/null", "notif": "State: synthetic day " + n + "\\nDecision: ship it first"}
def deliver(cfg, title, body, url=None, env=None):
    env = dict(os.environ if env is None else env)
    with open(os.path.join(env["HOME"], "deliver-env.txt"), "a") as f:
        f.write(repr(env.get("KEVIN_PUSH_ONCE")) + "\\n")
    r = subprocess.run([env["KEVIN_PUSH_BIN"], "limitless", title, body], env=env,
                       capture_output=True, text=True, timeout=30)
    return {"rc": r.returncode, "shown": r.stdout.strip().replace("kevin-push: ", "")}
'''


class BriefSenders(unittest.TestCase):
    """bin/limitless-brief and bin/limitless-jobs, both through the real bin/kevin-push and a fake hermes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        lib = self.home / ".local/lib"
        lib.mkdir(parents=True)
        (lib / "limitless_loop.py").write_text(FAKE_LOOP)
        self.st = self.home / "state"
        self.st.mkdir()
        bindir = self.home / "bin"
        bindir.mkdir()
        hermes = bindir / "hermes"
        hermes.write_text("#!/bin/sh\necho called >> \"$HOME/hermes-calls\"\nexit 0\n")
        hermes.chmod(0o755)
        self.env = {"HOME": str(self.home), "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
                    "LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.home / "no-config.json"),
                    "LIMITLESS_SLEEPMODE": str(self.st / "sleepmode.jsonl"), "KEVIN_PUSH_BIN": str(KEVIN_PUSH)}

    def tearDown(self):
        self.tmp.cleanup()

    def wake(self, off):
        now = time.time()
        write_rows(self.st / "sleepmode.jsonl", [{"at": iso(off - 8 * H), "on": True}, {"at": iso(off), "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": iso(now - 30), "ok": True}))
        write_rows(self.st / "unlocks.jsonl", [{"at": iso(now - 60)}])
        return f"wake_brief:{int(off)}"

    def brief(self, env=None):
        return subprocess.run([sys.executable, "-I", str(BRIEF), "send"], env=child_env(env or self.env),
                              capture_output=True, text=True, timeout=30)

    def jobs_cli(self):
        return subprocess.run([sys.executable, "-I", str(JOBS), "--send"], env=child_env(self.env),
                              capture_output=True, text=True, timeout=30)

    def shown(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["notify"]["shown"]

    def deliveries(self):
        p = self.home / "hermes-calls"
        return p.read_text().count("called") if p.exists() else 0

    def claimed(self):
        p = self.home / ".local/state/kevin-push/sent.json"
        return [r.get("once") for r in json.loads(p.read_text())] if p.exists() else []

    def passed_once(self):
        return (self.home / "deliver-env.txt").read_text().splitlines()

    def test_brief_first_then_jobs_is_one_delivery(self):
        key = self.wake(int(time.time() - 0.2 * H))
        self.assertEqual(self.shown(self.brief()), "telegram")
        r = self.jobs_cli()
        self.assertEqual(self.deliveries(), 1, r.stdout)
        self.assertIn("Wake-up brief: drop", r.stdout)
        self.assertIn(send_gate.ONCE_DROP, r.stdout)
        self.assertEqual(self.claimed(), [key])

    def test_jobs_first_then_brief_is_one_delivery(self):
        key = self.wake(int(time.time() - 0.2 * H))
        r = self.jobs_cli()
        self.assertIn("Wake-up brief: deliver", r.stdout)
        self.assertEqual(self.shown(self.brief()), f"log ({send_gate.ONCE_DROP})")
        self.assertEqual(self.deliveries(), 1)
        # limitless-jobs sent it by running limitless-brief send, so both runs passed this wake's key.
        self.assertEqual(self.passed_once(), [repr(key), repr(key)])

    def test_a_later_wake_is_a_new_key_and_is_delivered(self):
        first = self.wake(int(time.time() - 11 * H))
        self.assertEqual(self.shown(self.brief()), "telegram")
        second = self.wake(int(time.time() - 0.2 * H))
        (self.home / "brief-day.txt").write_text("2")    # a new day's brief has new words
        self.assertNotEqual(first, second)
        self.assertEqual(self.shown(self.brief()), "telegram")
        self.assertEqual(self.deliveries(), 2)
        self.assertEqual(self.claimed(), [first, second])

    def test_no_wake_trigger_sends_with_no_key_and_outside_key_never_leaks(self):
        self.assertEqual(self.shown(self.brief(dict(self.env, KEVIN_PUSH_ONCE="wake_brief:123"))), "telegram")
        self.assertEqual(self.passed_once(), ["None"])
        self.assertEqual(self.claimed(), [None])

    def test_outside_key_is_replaced_by_this_wakes_key(self):
        key = self.wake(int(time.time() - 0.2 * H))
        self.assertEqual(self.shown(self.brief(dict(self.env, KEVIN_PUSH_ONCE="wake_brief:123"))), "telegram")
        self.assertEqual(self.passed_once(), [repr(key)])

    def test_broken_state_still_sends_as_today(self):
        (self.st / "sleepmode.jsonl").write_text("{not json\n")
        self.assertEqual(self.shown(self.brief()), "telegram")
        self.assertEqual(self.passed_once(), ["None"])


if __name__ == "__main__":
    unittest.main()
