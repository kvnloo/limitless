"""bin/kevin-push --once KEY (or $KEVIN_PUSH_ONCE): the first message per event key goes out.

Fake `hermes` on PATH and a temp HOME; nothing is really sent. Synthetic data only.
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
KEY = "wake_brief:1999990000"


class KevinPushOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        fakebin = self.home / "fakebin"
        fakebin.mkdir()
        hermes = fakebin / "hermes"
        # counts its calls; exits $FAKE_HERMES_RC (default 0)
        hermes.write_text("#!/bin/sh\necho called >> \"$HOME/hermes-calls\"\nexit ${FAKE_HERMES_RC:-0}\n")
        hermes.chmod(hermes.stat().st_mode | stat.S_IEXEC)
        self.sleepmode = self.home / "sleepmode.jsonl"
        self.env = dict(os.environ, HOME=str(self.home), PATH=f"{fakebin}:{os.environ['PATH']}",
                        LIMITLESS_SLEEPMODE=str(self.sleepmode), CIRCADIAN_CLASS="decision")
        self.env.pop("KEVIN_PUSH_ONCE", None)
        self.st = self.home / ".local/state/kevin-push"

    def tearDown(self):
        self.tmp.cleanup()

    def push(self, *args, **env):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(dict(self.env, **env)),
                              capture_output=True, text=True, timeout=30)

    def calls(self):
        p = self.home / "hermes-calls"
        return p.read_text().count("called") if p.exists() else 0

    def sent(self):
        p = self.st / "sent.json"
        return json.loads(p.read_text()) if p.exists() else []

    def how(self):
        return json.loads((self.st / "log.jsonl").read_text().splitlines()[-1])["how"]

    def sleep_mode(self, on):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.sleepmode.write_text(json.dumps({"at": now, "on": on}) + "\n")
        self.sleepmode.with_name("sleepmode-poll.json").write_text(json.dumps({"at": now, "ok": True}))

    def test_two_texts_one_key_one_delivered_one_dropped(self):
        r1 = self.push("limitless", "Wake-up brief", "You are up. Your brief comes next.", "--once", KEY)
        r2 = self.push("limitless", "Wake-up brief", "Good morning: three things today.", "--once", KEY,
                       KEVIN_PUSH_STRICT="1")
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertEqual(r1.stdout.strip(), "kevin-push: telegram")
        self.assertEqual(r2.stdout.strip(), "kevin-push: log (already sent for this event)")
        self.assertEqual(r2.returncode, 3, "strict: a dropped message is not delivered")
        self.assertEqual(self.calls(), 1)
        self.assertEqual([s.get("once") for s in self.sent()], [KEY])

    def test_flag_before_the_arguments(self):
        self.push("--once", KEY, "limitless", "Wake-up brief", "one")
        r = self.push("--once", KEY, "limitless", "Wake-up brief", "two")
        self.assertEqual(r.stdout.strip(), "kevin-push: log (already sent for this event)")
        self.assertEqual(self.calls(), 1)

    def test_key_from_env(self):
        self.push("limitless", "Wake-up brief", "one", KEVIN_PUSH_ONCE=KEY)
        r = self.push("limitless", "Wake-up brief", "two", KEVIN_PUSH_ONCE=KEY)
        self.assertEqual(self.how(), "log (already sent for this event)", r.stdout)
        self.assertEqual(self.calls(), 1)
        self.assertEqual(self.sent()[0]["once"], KEY)

    def test_flag_wins_over_env(self):
        self.push("limitless", "Wake-up brief", "one", "--once", KEY)
        r = self.push("limitless", "Wake-up brief", "two", "--once", "wake_brief:1999999999", KEVIN_PUSH_ONCE=KEY)
        self.assertEqual(r.stdout.strip(), "kevin-push: telegram")

    def test_same_text_other_key_is_still_a_12h_duplicate(self):
        self.push("limitless", "Wake-up brief", "same words", "--once", KEY)
        r = self.push("limitless", "Wake-up brief", "same words", "--once", "wake_brief:1999999999")
        self.assertEqual(r.stdout.strip(), "kevin-push: log (duplicate)")
        self.assertEqual(self.calls(), 1)

    def test_failed_send_never_claims_the_key(self):
        r1 = self.push("limitless", "Wake-up brief", "one", "--once", KEY, FAKE_HERMES_RC="1")
        self.assertEqual(r1.stdout.strip(), "kevin-push: log (telegram rc=1)")
        self.assertEqual(self.sent(), [])
        r2 = self.push("limitless", "Wake-up brief", "two", "--once", KEY)
        self.assertEqual(r2.stdout.strip(), "kevin-push: telegram")
        self.assertEqual([s.get("once") for s in self.sent()], [KEY])

    def test_held_send_never_claims_the_key(self):
        self.sleep_mode(True)
        r1 = self.push("x", "Pick one", "one", "--once", "decision:1999990000")
        self.assertEqual(r1.stdout.strip(), "kevin-push: held (sleep mode)")
        self.assertEqual(self.sent(), [])
        self.sleep_mode(False)
        r2 = self.push("x", "Pick one", "two", "--once", "decision:1999990000")
        self.assertEqual(r2.stdout.strip(), "kevin-push: telegram")

    def test_log_only_send_never_claims_the_key(self):
        self.push("x", "Note", "fyi", "--once", KEY, CIRCADIAN_CLASS="report")
        self.assertEqual(self.sent(), [])

    def test_without_a_key_nothing_changes(self):
        self.push("limitless", "Wake-up brief", "one")
        r = self.push("limitless", "Wake-up brief", "two")
        self.assertEqual(r.stdout.strip(), "kevin-push: telegram")
        self.assertNotIn("once", self.sent()[0])

    def test_once_needs_a_value_and_three_arguments(self):
        self.assertEqual(self.push("limitless", "Wake-up brief", "one", "--once").returncode, 2)
        self.assertEqual(self.push("--once", KEY, "limitless", "Wake-up brief").returncode, 2)
        self.assertEqual(self.calls(), 0)

    def test_card_ids_never_reach_the_sent_log(self):
        self.push("limitless", "Wake-up brief", "one t_510c250d", "--once", "wake_brief:t_510c250d:1999990000")
        written = (self.st / "sent.json").read_text() + (self.st / "log.jsonl").read_text()
        self.assertNotIn("t_510c250d", written)


if __name__ == "__main__":
    unittest.main()
