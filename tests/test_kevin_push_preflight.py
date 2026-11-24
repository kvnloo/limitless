"""bin/kevin-push checks its sender profile before it sends: a profile that cannot exist starts no hermes.

On a ``send`` verdict kevin-push asks push_sender.check (files only). BROKEN: no hermes is started, the row is
logged ``log (no sender profile)`` and the exit is that of a failed send (0, or 3 with KEVIN_PUSH_STRICT=1).
SET and ``unknown: ...`` try the send as before. No fallback sender, no other profile. A fake `hermes` on PATH
records each call; synthetic Hermes homes, a temp HOME, synthetic names only; nothing is sent.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import shlex
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

from limitless import push_sender  # noqa: E402

CLI = ROOT / "bin" / "kevin-push"
NO_SENDER = "log (no sender profile)"
KEY = "wake_brief:1999990000"


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


class Preflight(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        fakebin = self.home / "fakebin"
        fakebin.mkdir()
        hermes = fakebin / "hermes"
        hermes.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$HOME/hermes-calls\"\nexit 0\n")
        hermes.chmod(hermes.stat().st_mode | stat.S_IEXEC)
        self.hermes_home = self.home / "hermes-home"          # a synthetic Hermes home with no profiles yet
        self.hermes_home.mkdir()
        self.state = self.home / "state"
        self.state.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("KEVIN_PUSH_")}
        self.env.update(HOME=str(self.home), PATH=f"{fakebin}:{os.environ['PATH']}",
                        HERMES_HOME=str(self.hermes_home), LIMITLESS_STATE=str(self.state),
                        LIMITLESS_CONFIG=str(self.home / "none.json"),
                        LIMITLESS_SLEEPMODE=str(self.state / "sleepmode.jsonl"), CIRCADIAN_CLASS="decision")
        self.st = self.home / ".local/state/kevin-push"

    def tearDown(self):
        self.tmp.cleanup()

    def profile(self, name):
        (self.hermes_home / "profiles" / name).mkdir(parents=True)

    def push(self, *args, **env):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(self.env, **env),
                              capture_output=True, text=True, timeout=30)

    def calls(self):
        p = self.home / "hermes-calls"
        return p.read_text().splitlines() if p.exists() else []

    def logs(self):
        return [json.loads(x) for x in (self.st / "log.jsonl").read_text().splitlines()]

    def sent(self):
        p = self.st / "sent.json"
        return json.loads(p.read_text()) if p.exists() else []

    def sleep(self, on):
        now = time.time()
        (self.state / "sleepmode.jsonl").write_text(json.dumps({"at": iso(now - 3600), "on": on}) + "\n")
        (self.state / "sleepmode-poll.json").write_text(json.dumps({"at": iso(now - 30), "ok": True}))

    # -- the three answers of push_sender.check ---------------------------------------------------------

    def test_a_missing_sender_profile_starts_no_hermes_and_logs_its_own_row(self):
        self.assertEqual(push_sender.check({}, {"HERMES_HOME": str(self.hermes_home)}), push_sender.BROKEN)
        r = self.push("x", "Pick one", "Keep the loop?\nReply: Yes / No")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), f"kevin-push: {NO_SENDER}")
        self.assertEqual(self.calls(), [])
        row = self.logs()[-1]
        self.assertEqual(row["how"], NO_SENDER)
        self.assertEqual(row["title"], "Pick one")
        self.assertEqual(self.sent(), [])                     # not a send: no dedupe row, no cap use

    def test_strict_still_exits_non_zero_when_the_sender_is_missing(self):
        r = self.push("x", "Pick one", "Keep the loop?", KEVIN_PUSH_STRICT="1")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_sender_profile_that_exists_is_used(self):
        self.profile("intake")
        r = self.push("x", "Pick one", "Keep the loop?", KEVIN_PUSH_STRICT="1")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "kevin-push: telegram"), r.stderr)
        self.assertEqual(len(self.calls()), 1)
        self.assertTrue(self.calls()[0].startswith("-p intake send --to telegram:kevin"))

    def test_unknown_keeps_todays_behaviour_and_tries_the_send(self):
        gone = self.home / "no-such-hermes-home"
        self.assertTrue(push_sender.check({}, {"HERMES_HOME": str(gone)}).startswith(push_sender.UNKNOWN_PREFIX))
        r = self.push("x", "Pick one", "Keep the loop?", HERMES_HOME=str(gone))
        self.assertEqual(r.stdout.strip(), "kevin-push: telegram", r.stderr)
        self.assertEqual(len(self.calls()), 1)

    def test_the_default_profile_is_always_tried(self):
        r = self.push("x", "Pick one", "Keep the loop?", KEVIN_PUSH_PROFILE="default")
        self.assertEqual(r.stdout.strip(), "kevin-push: telegram", r.stderr)
        self.assertEqual(len(self.calls()), 1)

    def test_never_a_fallback_sender_or_another_profile(self):
        self.profile("intake")                                 # the built-in default exists, the chosen one not
        (self.home / "cfg.json").write_text(json.dumps({"push_profile": "sender-a"}))
        r = self.push("x", "Pick one", "Keep the loop?", LIMITLESS_CONFIG=str(self.home / "cfg.json"))
        self.assertEqual(r.stdout.strip(), f"kevin-push: {NO_SENDER}", r.stderr)
        self.assertEqual(self.calls(), [])
        r = self.push("x", "Pick two", "Keep the loop?", KEVIN_PUSH_PROFILE="sender-b")
        self.assertEqual(r.stdout.strip(), f"kevin-push: {NO_SENDER}", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_once_key_is_not_claimed_so_the_retry_goes_out_once_the_profile_is_back(self):
        r = self.push("limitless", "Wake-up brief", "Good morning.", "--once", KEY, CIRCADIAN_CLASS="report")
        self.assertEqual(r.stdout.strip(), f"kevin-push: {NO_SENDER}", r.stderr)
        self.profile("intake")
        r = self.push("limitless", "Wake-up brief", "Good morning.", "--once", KEY, CIRCADIAN_CLASS="report")
        self.assertEqual(r.stdout.strip(), "kevin-push: telegram", r.stderr)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual([x["how"] for x in self.logs()], [NO_SENDER, "telegram"])

    def test_only_a_send_verdict_is_checked(self):
        r = self.push("x", "Sync report", "all synced", CIRCADIAN_CLASS="report")
        self.assertEqual(r.stdout.strip(), "kevin-push: log", r.stderr)
        self.assertEqual(self.calls(), [])

    # -- held messages released later go through the same check -------------------------------------------

    def test_a_held_brief_released_after_sleep_starts_no_hermes_while_the_sender_is_missing(self):
        self.sleep(True)
        r = self.push("limitless", "Wake-up brief", "Good morning.", "--once", KEY, CIRCADIAN_CLASS="report")
        self.assertEqual(r.stdout.strip(), "kevin-push: held (sleep mode)", r.stderr)
        self.sleep(False)
        r = self.push("limitless", "Wake-up brief", "Good morning.", "--once", KEY, CIRCADIAN_CLASS="report")
        self.assertEqual(r.stdout.strip(), f"kevin-push: {NO_SENDER}", r.stderr)
        r = self.push("limitless", "Back from nap", "Held while you slept: Wake-up brief",
                      CIRCADIAN_CLASS="report")
        self.assertEqual(r.stdout.strip(), f"kevin-push: {NO_SENDER}", r.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual([x["how"] for x in self.logs()], ["held (sleep mode)", NO_SENDER, NO_SENDER])
        self.assertEqual(self.sent(), [])

    def test_a_held_brief_released_with_the_sender_set_is_sent(self):
        self.profile("intake")
        self.sleep(True)
        self.push("limitless", "Wake-up brief", "Good morning.", "--once", KEY, CIRCADIAN_CLASS="report")
        self.sleep(False)
        r = self.push("limitless", "Back from nap", "Held while you slept: Wake-up brief", CIRCADIAN_CLASS="report")
        self.assertEqual(r.stdout.strip(), "kevin-push: telegram", r.stderr)
        self.assertEqual(len(self.calls()), 1)

    # -- docs ------------------------------------------------------------------------------------------------

    def test_the_docstring_example_is_the_real_output(self):
        doc = CLI.read_text().split('"""')[1]
        lines = doc.splitlines()
        i = next(n for n, ln in enumerate(lines) if ln.strip().startswith("$ CIRCADIAN_CLASS=decision kevin-push"))
        cmd, want = shlex.split(lines[i].strip()[2:]), lines[i + 1].strip()
        cls = cmd.pop(0).split("=", 1)[1]
        self.assertEqual(cmd[0], "kevin-push")
        r = self.push(*cmd[1:], CIRCADIAN_CLASS=cls)
        self.assertEqual(r.stdout.strip(), want, r.stderr)
        self.assertEqual(want, f"kevin-push: {NO_SENDER}")
        self.assertEqual(self.calls(), [])
        for word in (NO_SENDER, "KEVIN_PUSH_STRICT", "fallback", "owner's call", "held"):
            self.assertIn(word, doc)


if __name__ == "__main__":
    unittest.main()
