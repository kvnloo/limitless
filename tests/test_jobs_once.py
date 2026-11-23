"""jobs_runner: every send carries the event key <job>:<trigger event time>. Synthetic data only.

NOW is an arbitrary epoch; only differences between times matter. Nothing really sends: the push
is a fake, and the CLI tests put a fake `hermes` (or a fake kevin-push) on PATH.
"""
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, jobs_runner, send_gate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-jobs"
KEVIN_PUSH = ROOT / "bin" / "kevin-push"
NOW = 2_000_000_000.0
H = 3600.0


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class OncePush:
    """A fake push that takes the event key, as bin/limitless-jobs does."""

    def __init__(self, result="telegram"):
        self.result, self.calls = result, []

    def __call__(self, title, body, once=None):
        self.calls.append((title, body, once))
        return self.result


class OnceKey(unittest.TestCase):
    def test_key_is_job_name_and_event_time(self):
        self.assertEqual(jobs_runner.once_key(jobs.WAKE_BRIEF, NOW - 0.2 * H), f"wake_brief:{int(NOW - 0.2 * H)}")

    def test_key_has_no_digits_but_the_event_time_and_no_card_ids(self):
        # A habit with numbers and a card id in its words: none of it reaches the key.
        spec = jobs.habit_checkin({"habit": "walk 45 min t_510c250d", "cue": "after 7 coffees"})
        k = jobs_runner.once_key(spec, 1_999_000_000.0)
        self.assertRegex(k, r"^[a-z_]+:\d+$")
        self.assertEqual(re.sub(r"\D", "", k), "1999000000")
        self.assertNotIn("t_510c250d", k)
        self.assertEqual(send_gate.scrub(k), k)

    def test_every_spec_key_is_name_and_time_only(self):
        for spec in jobs.SPECS.values():
            k = jobs_runner.once_key(spec, 1_999_000_123.75)
            self.assertEqual(k, f"{spec.name}:1999000123")


class RunnerPassesKey(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json")}
        self.off = NOW - 0.2 * H
        write_rows(self.st / "sleepmode.jsonl", [{"at": NOW - 8.5 * H, "on": True}, {"at": self.off, "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
        write_rows(self.st / "unlocks.jsonl", [{"at": NOW - 120}])

    def tearDown(self):
        self.tmp.cleanup()

    def once(self, push, now=NOW):
        return {r["job"]: r for r in jobs_runner.run_once(self.st, now, push=push, dry_run=False,
                                                          env=self.env, home=self.root)}

    def test_send_carries_the_wake_key(self):
        push = OncePush()
        self.once(push)
        self.assertEqual(push.calls, [("Wake-up brief", jobs_runner.body(jobs.WAKE_BRIEF),
                                       f"wake_brief:{int(self.off)}")])

    def test_polls_of_one_wake_share_one_key(self):
        push = OncePush("log (telegram rc=1)")
        self.once(push)
        self.once(push, now=NOW + 300)
        self.once(push, now=NOW + 600)
        self.assertEqual({c[2] for c in push.calls}, {f"wake_brief:{int(self.off)}"})
        self.assertEqual(len(push.calls), 3)

    def test_a_push_without_a_key_parameter_still_works(self):
        calls = []
        self.once(lambda title, body: calls.append(title) or "telegram")
        self.assertEqual(calls, ["Wake-up brief"])

    def test_already_sent_for_this_event_is_a_drop_not_a_retry(self):
        row = self.once(OncePush(f"log ({send_gate.ONCE_DROP}) (exit 3)"))["Wake-up brief"]
        self.assertEqual(row["action"], jobs.DROP)
        self.assertIn(send_gate.ONCE_DROP, row["reason"])
        self.assertFalse((self.st / "jobs-sent.jsonl").exists(), "another sender's delivery is not ours")


class TwoSenders(unittest.TestCase):
    """bin/limitless-jobs and an older sender, both through the real bin/kevin-push and a fake hermes.

    The job is "Back from nap", which limitless-jobs pushes itself; the wake brief goes through
    limitless-brief instead (tests/test_brief_once_cli.py)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        now = time.time()
        self.off = int(now - 0.1 * H)
        write_rows(self.st / "sleepmode.jsonl", [{"at": iso(now - 12 * H), "on": True}, {"at": iso(now - 3 * H), "on": False},
                                                 {"at": iso(now - 1 * H), "on": True}, {"at": iso(self.off), "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": iso(now - 30), "ok": True}))
        write_rows(self.st / "unlocks.jsonl", [{"at": iso(now - 60)}])
        bindir = self.home / "bin"
        bindir.mkdir()
        hermes = bindir / "hermes"
        hermes.write_text("#!/bin/sh\necho called >> \"$HOME/hermes-calls\"\nexit 0\n")
        hermes.chmod(0o755)
        self.env = {"HOME": str(self.home), "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
                    "LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.home / "no-config.json"),
                    "LIMITLESS_SLEEPMODE": str(self.st / "sleepmode.jsonl"), "KEVIN_PUSH_BIN": str(KEVIN_PUSH)}
        self.key = f"nap:{self.off}"

    def tearDown(self):
        self.tmp.cleanup()

    def jobs_cli(self):
        return subprocess.run([sys.executable, "-I", str(CLI), "--send"], env=self.env,
                              capture_output=True, text=True, timeout=30)

    def older_sender(self, body, key):
        return subprocess.run([sys.executable, "-I", str(KEVIN_PUSH), "limitless", "Back from nap", body,
                               "--once", key], env=self.env, capture_output=True, text=True, timeout=30)

    def deliveries(self):
        p = self.home / "hermes-calls"
        return p.read_text().count("called") if p.exists() else 0

    def test_older_sender_first_then_runner_other_text_same_key(self):
        self.assertEqual(self.older_sender("Welcome back, synthetic re-entry note.", self.key).stdout.strip(),
                         "kevin-push: telegram")
        r = self.jobs_cli()
        self.assertEqual(self.deliveries(), 1, r.stdout)
        self.assertIn("Back from nap: drop", r.stdout)
        self.assertIn(send_gate.ONCE_DROP, r.stdout)

    def test_runner_first_then_older_sender_other_text_same_key(self):
        r = self.jobs_cli()
        self.assertIn("Back from nap: deliver", r.stdout)
        o = self.older_sender("Welcome back, synthetic re-entry note.", self.key)
        self.assertEqual(o.stdout.strip(), f"kevin-push: log ({send_gate.ONCE_DROP})")
        self.assertEqual(self.deliveries(), 1)

    def test_same_text_other_key_is_still_a_12h_duplicate(self):
        self.older_sender(jobs_runner.body(jobs.NAP), "older-script:nap")
        r = self.jobs_cli()
        self.assertEqual(self.deliveries(), 1, r.stdout)
        self.assertIn("log (duplicate)", r.stdout)

    def test_sent_log_key_has_only_the_event_time_digits(self):
        self.jobs_cli()
        rows = json.loads((self.home / ".local/state/kevin-push/sent.json").read_text())
        self.assertEqual([r.get("once") for r in rows], [self.key])


if __name__ == "__main__":
    unittest.main()
