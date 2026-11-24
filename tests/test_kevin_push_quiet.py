"""bin/kevin-push with quiet.json and the why-now line, end to end with a fake `hermes`. Nothing really sends.

Synthetic data only.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "kevin-push"
END = "<<END>>"


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")
AW = "you are awake and this fits any moment"   # decision_window.plain("anytime job and awake")


class KevinPushQuiet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        fakebin = self.home / "fakebin"
        fakebin.mkdir()
        hermes = fakebin / "hermes"
        # appends every body it was asked to send to $HOME/bodies, one END marker after each
        hermes.write_text("#!/bin/sh\nwhile [ $# -gt 0 ]; do if [ \"$1\" = --file ]; then cat \"$2\" >> \"$HOME/bodies\";"
                          " printf '\\n" + END + "\\n' >> \"$HOME/bodies\"; fi; shift; done\n")
        hermes.chmod(hermes.stat().st_mode | stat.S_IEXEC)
        self.state = self.home / "state"
        self.state.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), PATH=f"{fakebin}:{os.environ['PATH']}",
                        LIMITLESS_STATE=str(self.state), LIMITLESS_CONFIG=str(self.home / "none.json"),
                        LIMITLESS_SLEEPMODE=str(self.state / "sleepmode.jsonl"), CIRCADIAN_CLASS="decision")
        for k in ("KEVIN_PUSH_ONCE", "KEVIN_PUSH_WHY", "KEVIN_PUSH_STRICT", "LIMITLESS_OWNER_DBS",
                  "LIMITLESS_OWNER_BEACONS", "LIMITLESS_HERMES_DB"):
            self.env.pop(k, None)
        self.st = self.home / ".local/state/kevin-push"
        self.now = time.time()

    def tearDown(self):
        self.tmp.cleanup()

    def quiet(self, mode, since=None):
        (self.state / "quiet.json").write_text(json.dumps({"mode": mode, "since": iso(since or self.now - 600)}))

    def asleep(self):
        (self.state / "sleepmode.jsonl").write_text(json.dumps({"at": iso(self.now - 3600), "on": True}) + "\n")
        (self.state / "sleepmode-poll.json").write_text(json.dumps({"at": iso(self.now - 30), "ok": True}))

    def push(self, *args, **env):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(dict(self.env, **env)),
                              capture_output=True, text=True, timeout=30)

    def bodies(self):
        p = self.home / "bodies"
        if not p.exists():
            return []
        return [b.strip("\n") for b in p.read_text().split(END + "\n") if b.strip()]

    def last_log(self):
        return json.loads((self.st / "log.jsonl").read_text().splitlines()[-1])

    def sent(self):
        p = self.st / "sent.json"
        return json.loads(p.read_text()) if p.exists() else []

    # quiet drops, never holds or queues

    def test_off_drops_a_decision_with_a_quiet_reason(self):
        self.quiet("off")
        r = self.push("x", "Pick one", "keep the loop", KEVIN_PUSH_STRICT="1")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertEqual(self.last_log()["how"], "log (quiet: off until you reply on)")
        self.assertIn("kevin-push: log (quiet: off until you reply on)", r.stdout)
        self.assertEqual(self.bodies(), [])

    def test_off_drops_critical_too(self):
        self.quiet("off")
        self.push("x", "Fire", "now", CIRCADIAN_CLASS="critical")
        self.assertEqual(self.bodies(), [])
        self.assertTrue(self.last_log()["how"].startswith("log (quiet: "))

    def test_off_drops_the_wake_brief(self):
        self.quiet("off")
        self.push("limitless", "Wake-up brief", "the brief", CIRCADIAN_CLASS="digest")
        self.assertEqual(self.bodies(), [])

    def test_quiet_while_asleep_is_dropped_not_held_for_later(self):
        self.quiet("off")
        self.asleep()
        self.push("x", "Pick one", "keep the loop")
        self.assertFalse((self.st / "held.jsonl").exists())
        self.assertTrue(self.last_log()["how"].startswith("log (quiet: "))

    def test_asleep_without_quiet_still_holds(self):
        self.asleep()
        self.push("x", "Pick one", "keep the loop")
        self.assertTrue((self.st / "held.jsonl").exists())

    def test_a_dropped_event_stays_dropped_after_quiet_ends(self):
        self.quiet("off")
        self.push("limitless", "Wake-up brief", "the brief", "--once", "wake_brief:1999990000")
        self.assertEqual(self.sent(), [{"t": self.sent()[0]["t"], "once": "wake_brief:1999990000", "quiet": True}])
        self.quiet("on")
        self.push("limitless", "Wake-up brief", "the brief", "--once", "wake_brief:1999990000")
        self.assertEqual(self.bodies(), [])
        self.assertEqual(self.last_log()["how"], "log (already sent for this event)")

    def test_quiet_drops_do_not_fill_the_daily_cap(self):
        self.quiet("off")
        for i in range(8):
            self.push("x", f"Pick {chr(97 + i)}", "body", "--once", f"k:{i}")
        self.quiet("on")
        self.push("x", "Pick now", "body")
        self.assertEqual(len(self.bodies()), 1)

    def test_quiet_tonight_ends_at_the_wake(self):
        self.quiet("quiet_tonight")
        self.push("x", "Pick one", "body")
        self.assertEqual(self.bodies(), [])
        (self.state / "events.jsonl").write_text(json.dumps({"event": "wake", "at": iso(self.now - 60)}) + "\n")
        self.push("x", "Pick two", "body")
        self.assertEqual(len(self.bodies()), 1)

    def test_snooze_with_no_message_source_fails_open(self):
        self.quiet("snoozed")
        self.push("x", "Pick one", "body")
        self.assertEqual(len(self.bodies()), 1)

    def test_snooze_holds_until_a_newer_message_in_a_beacon(self):
        beacon = self.home / "beacon.json"
        beacon.write_text(json.dumps({"at": iso(self.now - 600), "v": 1}))
        self.quiet("snoozed", self.now - 600)
        self.push("x", "Pick one", "body", LIMITLESS_OWNER_BEACONS=str(beacon))
        self.assertEqual(self.bodies(), [])
        beacon.write_text(json.dumps({"at": iso(self.now - 5), "v": 1}))
        self.push("x", "Pick two", "body", LIMITLESS_OWNER_BEACONS=str(beacon))
        self.assertEqual(len(self.bodies()), 1)

    def test_broken_quiet_file_fails_open(self):
        (self.state / "quiet.json").write_text("{nope")
        self.push("x", "Pick one", "body")
        self.assertEqual(len(self.bodies()), 1)

    # the why-now line

    def test_no_message_leaves_without_a_why_now_line(self):
        self.push("x", "Pick one", "Decision: t_510c250d: keep the loop")
        self.push("x", "Fire", "now", CIRCADIAN_CLASS="critical")
        self.push("limitless", "Wake-up brief", "line one\nline two", CIRCADIAN_CLASS="digest")
        self.push("limitless", "Back from nap", "welcome back")
        self.push("x", "Window", "pick", "--why", "wake event; peak window open (since 1999990000)")
        self.push("x", "Empty", "")             # six: the daily cap
        bodies = self.bodies()
        logs = [json.loads(x) for x in (self.st / "log.jsonl").read_text().splitlines()]
        self.assertEqual(len(bodies), 6)
        self.assertEqual(sum(1 for x in logs if x["how"] == "telegram"), 6)
        for b in bodies:
            last = b.splitlines()[-1]
            self.assertTrue(last.startswith("Why now: "), b)
            self.assertFalse(any(c.isdigit() for c in last), last)
            self.assertEqual(sum(1 for ln in b.splitlines() if ln.startswith("Why now: ")), 1, b)
            self.assertNotIn("t_510c250d", b)

    def test_why_now_lines_say_why(self):
        self.push("limitless", "Wake-up brief", "the brief", CIRCADIAN_CLASS="digest")
        self.push("x", "Window", "pick", "--why", "wake event; peak window open (since 1999990000)")
        self.push("x", "Fire", "now", CIRCADIAN_CLASS="critical")
        self.push("x", "Env why", "pick", KEVIN_PUSH_WHY="trough window open")
        self.push("x", "Plain", "pick")
        lasts = [b.splitlines()[-1] for b in self.bodies()]
        self.assertEqual(lasts, ["Why now: you woke up", "Why now: you woke up; your focus is high right now",
                                 "Why now: this is urgent, so it comes whatever you are doing",
                                 "Why now: it is a lighter moment, fine for a short read",
                                 f"Why now: {AW}"])

    def test_the_why_line_does_not_change_the_dedupe_key(self):
        self.push("x", "Pick one", "body", "--why", "trough window open")
        self.push("x", "Pick one", "body", "--why", "peak window open")
        self.assertEqual(len(self.bodies()), 1)
        self.assertEqual(self.last_log()["how"], "log (duplicate)")

    def test_why_without_a_value_is_a_usage_error(self):
        r = self.push("x", "T", "b", "--why")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
