"""End to end: one MIQ prompt per night, a shell sender with its own cue and limitless-jobs --send.

The shell sender asks `bin/limitless-once-key miq --night` for tonight's key before any wind-down
event exists; a later wind-down event and limitless-jobs --send get the same key, so kevin-push lets
only the first through. Both go through the real bin/kevin-push with a temp HOME and a fake `hermes`
on PATH that only records its arguments, so nothing really sends. Synthetic data only.

The local zone is a fixed offset (TZ) chosen so local time is shortly after midnight, so the test is
the same whatever the clock says: the night date is a key, never a trigger.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import send_gate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / "bin" / "limitless-jobs"
KEVIN_PUSH = ROOT / "bin" / "kevin-push"
MIQ = "MIQ for tonight?"
SHELL_NIGHT = ('KEVIN_PUSH_ONCE=$(bin/limitless-once-key miq --night) '
               'kevin-push limitless "MIQ for tonight?" "Wind-down: pick the one thing for tomorrow."')
H = 3600


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def zone_after_midnight(now):
    """(TZ string, tzinfo): a whole-hour offset where `now` is local 01:30 to 02:30."""
    utc_h = (now % 86400) / 3600
    off = round(2 - utc_h)
    off = off + 24 if off < -12 else off
    return f"LCL{-off:+d}", timezone(timedelta(hours=off))


class TwoSendersOneNight(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        bindir = self.home / "bin"
        bindir.mkdir()
        hermes = bindir / "hermes"
        hermes.write_text("#!/bin/sh\necho \"$*\" >> \"$HOME/hermes-calls\"\nexit 0\n")
        hermes.chmod(0o755)
        kp = bindir / "kevin-push"                     # the real kevin-push, as the shell finds it on PATH
        kp.write_text(f"#!/bin/sh\nexec \"{sys.executable}\" -I \"{KEVIN_PUSH}\" \"$@\"\n")
        kp.chmod(0o755)
        self.att = self.home / "attention.json"
        self.now = time.time()
        tz_name, self.tz = zone_after_midnight(self.now)
        self.env = {"HOME": str(self.home), "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
                    "LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.home / "no-config.json"),
                    "LIMITLESS_SLEEPMODE": str(self.st / "sleepmode.jsonl"), "KEVIN_PUSH_BIN": str(kp),
                    "LIMITLESS_GLIDE_ATTENTION": str(self.att), "CIRCADIAN_CLASS": "decision", "TZ": tz_name}
        self.rows = []

    def tearDown(self):
        self.tmp.cleanup()

    def date(self, t):
        return datetime.fromtimestamp(t, self.tz).date().isoformat()

    def add(self, event, at):
        self.rows.append({"event": event, "at": iso(at)})
        write_rows(self.st / "events.jsonl", self.rows)

    def wake(self, ago_h):
        """A wake `ago_h` hours ago; the night key is its local date."""
        at = int(self.now - ago_h * H)
        self.add("wake", at)
        return f"miq:{self.date(at)}"

    def wind_down(self, ago_s=60):
        at = int(time.time() - ago_s)
        self.add("wind_down", at)
        self.att.write_text(json.dumps({"block": None, "resume": {"saved": at - 30}}))

    def shell_sender(self):
        return subprocess.run(["sh", "-c", SHELL_NIGHT], cwd=ROOT, env=child_env(self.env), capture_output=True, text=True,
                              timeout=60)

    def jobs_cli(self):
        return subprocess.run([sys.executable, "-I", str(JOBS), "--send"], env=child_env(self.env),
                              capture_output=True, text=True, timeout=60)

    def miq_deliveries(self):
        p = self.home / "hermes-calls"
        return sum(MIQ in line for line in p.read_text().splitlines()) if p.exists() else 0

    def claimed(self):
        p = self.home / ".local/state/kevin-push/sent.json"
        return [r.get("once") for r in json.loads(p.read_text()) if r.get("once", "").startswith("miq")] \
            if p.exists() else []

    def test_shell_sender_first_then_a_wind_down_event_is_one_prompt(self):
        key = self.wake(18)                           # woke yesterday; it is now just after midnight
        s = self.shell_sender()                       # its own cue: no wind-down event yet
        self.assertEqual(s.stdout.strip(), "kevin-push: telegram", s.stderr)
        self.wind_down()
        r = self.jobs_cli()
        self.assertIn(f"{MIQ}: drop", r.stdout)
        self.assertIn(send_gate.ONCE_DROP, r.stdout)
        self.assertEqual(self.miq_deliveries(), 1, r.stdout)
        self.assertEqual(self.claimed(), [key])
        self.assertEqual(key, f"miq:{self.date(self.now - 24 * H)}")   # the previous date

    def test_wind_down_event_first_then_the_shell_sender_is_one_prompt(self):
        key = self.wake(18)
        self.wind_down()
        r = self.jobs_cli()
        self.assertIn(f"{MIQ}: deliver", r.stdout)
        s = self.shell_sender()
        self.assertEqual(s.stdout.strip(), f"kevin-push: log ({send_gate.ONCE_DROP})", s.stderr)
        self.assertEqual(self.miq_deliveries(), 1)
        self.assertEqual(self.claimed(), [key])

    def test_the_next_night_is_a_new_key_and_one_more_prompt(self):
        first = self.wake(18)
        self.shell_sender()
        self.wind_down(ago_s=120)
        self.jobs_cli()
        self.assertEqual(self.miq_deliveries(), 1)
        second = self.wake(0.5)                       # the next waking day: a new night
        self.assertNotEqual(first, second)
        self.wind_down(ago_s=10)
        r = self.jobs_cli()
        self.assertIn(f"{MIQ}: deliver", r.stdout)
        s = self.shell_sender()
        self.assertEqual(s.stdout.strip(), f"kevin-push: log ({send_gate.ONCE_DROP})", s.stderr)
        self.assertEqual(self.miq_deliveries(), 2)
        self.assertEqual(self.claimed(), [first, second])


if __name__ == "__main__":
    unittest.main()
