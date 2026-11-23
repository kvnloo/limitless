"""bin/kevin-push while Sleep mode holds: each held message is kept once in held.jsonl, every hold still logged.

Fake `hermes` on PATH and a temp HOME; nothing is really sent. Synthetic data only.
"""
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
sys.path.insert(0, str(ROOT))

from limitless import delivery_audit  # noqa: E402
from limitless import held as held_mod  # noqa: E402

CLI = ROOT / "bin" / "kevin-push"
KEY = "wake_brief:1999990000"


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


class KevinPushHeld(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        fakebin = self.home / "fakebin"
        fakebin.mkdir()
        hermes = fakebin / "hermes"
        hermes.write_text("#!/bin/sh\necho called >> \"$HOME/hermes-calls\"\nexit 0\n")
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
        now = time.time()
        (self.state / "sleepmode.jsonl").write_text(json.dumps({"at": iso(now - 3600), "on": True}) + "\n")
        (self.state / "sleepmode-poll.json").write_text(json.dumps({"at": iso(now - 30), "ok": True}))

    def tearDown(self):
        self.tmp.cleanup()

    def push(self, *args, **env):
        r = subprocess.run([sys.executable, "-I", str(CLI), *args], env=dict(self.env, **env),
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "kevin-push: held (sleep mode)")
        return r

    def held(self):
        return [json.loads(x) for x in (self.st / "held.jsonl").read_text().splitlines()]

    def logs(self):
        return [json.loads(x) for x in (self.st / "log.jsonl").read_text().splitlines()]

    def calls(self):
        p = self.home / "hermes-calls"
        return p.read_text().count("called") if p.exists() else 0

    def test_the_wake_brief_retried_four_times_is_held_once_and_logged_four_times(self):
        for body in ("brief one", "brief two", "brief three", "brief four"):
            self.push("limitless", "Wake-up brief", body, "--once", KEY, CIRCADIAN_CLASS="digest")
        rows = self.held()
        self.assertEqual([(r["title"], r["body"], r["once"]) for r in rows], [("Wake-up brief", "brief four", KEY)])
        self.assertEqual([x["how"] for x in self.logs()], ["held (sleep mode)"] * 4)
        self.assertEqual([x["body"] for x in self.logs()], ["brief one", "brief two", "brief three", "brief four"])
        self.assertEqual(self.calls(), 0)

    def test_the_audit_still_sees_every_attempt_and_the_reader_lists_one(self):
        for _ in range(3):
            self.push("limitless", "Wake-up brief", "the brief", "--once", KEY, CIRCADIAN_CLASS="digest")
        rows, skipped = delivery_audit.read_log(self.st / "log.jsonl")
        self.assertEqual(([r["how"] for r in rows], skipped), (["held (sleep mode)"] * 3, 0))
        self.assertEqual([r["body"] for r in held_mod.rows(self.st / "held.jsonl")], ["the brief"])

    def test_same_title_and_body_without_a_key_is_held_once(self):
        self.push("x", "Pick one", "keep the loop")
        self.push("x", "Pick one", "keep the loop")
        self.assertEqual(len(self.held()), 1)
        self.assertEqual(len(self.logs()), 2)
        self.assertEqual(self.calls(), 0)

    def test_two_different_messages_are_both_held(self):
        self.push("x", "Pick one", "keep the loop")
        self.push("x", "Pick two", "keep the loop")
        self.assertEqual([r["title"] for r in self.held()], ["Pick one", "Pick two"])

    def test_a_why_line_only_difference_is_held_once(self):
        self.push("x", "Pick one", "keep the loop\nWhy now: you woke up")
        self.push("x", "Pick one", "keep the loop")
        self.assertEqual([r["body"] for r in self.held()], ["keep the loop"])

    def test_held_jsonl_is_private(self):
        self.push("x", "Pick one", "keep the loop")
        self.assertEqual(stat.S_IMODE((self.st / "held.jsonl").stat().st_mode), 0o600)

    def test_a_corrupt_line_is_kept_and_the_hold_still_works(self):
        self.st.mkdir(parents=True)
        (self.st / "held.jsonl").write_text("{nope\n")
        r = self.push("x", "Pick one", "keep the loop")
        self.assertNotIn("Traceback", r.stderr)
        lines = (self.st / "held.jsonl").read_text().splitlines()
        self.assertEqual(lines[0], "{nope")
        self.assertEqual(json.loads(lines[1])["title"], "Pick one")


if __name__ == "__main__":
    unittest.main()
