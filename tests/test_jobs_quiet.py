"""jobs_runner and bin/limitless-jobs with quiet: a quiet drop is a drop (never "the next run tries again"),
and the job's decision-window reason goes to kevin-push as --why. Synthetic data only; nothing really sends.
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

from limitless import jobs, jobs_runner  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-jobs"
KEVIN_PUSH = ROOT / "bin" / "kevin-push"
NOW = 2_000_000_000.0
H = 3600.0
END = "<<END>>"


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class WhyPush:
    """A fake push that takes the event key and the why reason."""

    def __init__(self, result="telegram"):
        self.result, self.calls = result, []

    def __call__(self, title, body, once=None, why=None):
        self.calls.append({"title": title, "once": once, "why": why})
        return self.result


class Runner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json")}
        write_rows(self.st / "sleepmode.jsonl", [{"at": NOW - 8.5 * H, "on": True}, {"at": NOW - 0.2 * H, "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
        write_rows(self.st / "unlocks.jsonl", [{"at": NOW - 120}])

    def tearDown(self):
        self.tmp.cleanup()

    def run_once(self, push):
        return {r["job"]: r for r in jobs_runner.run_once(self.st, NOW, push=push, dry_run=False,
                                                          env=self.env, home=self.root)}

    def test_a_quiet_drop_is_a_drop_not_a_retry(self):
        row = self.run_once(WhyPush("log (quiet: off until you reply on) (exit 3)"))["Wake-up brief"]
        self.assertEqual(row["action"], jobs.DROP)
        self.assertIn("quiet: off until you reply on", row["reason"])
        self.assertNotIn("tries again", row["reason"])
        self.assertFalse((self.st / "jobs-sent.jsonl").exists(), "a quiet drop is not a send")

    def test_the_brief_sender_reporting_quiet_is_a_drop(self):
        rows = jobs_runner.run_once(self.st, NOW, push=WhyPush(), dry_run=False, env=self.env, home=self.root,
                                    brief=lambda: "limitless-brief: log (quiet: snoozed until you write again) (exit 0)")
        row = {r["job"]: r for r in rows}["Wake-up brief"]
        self.assertEqual(row["action"], jobs.DROP)
        self.assertIn("quiet: snoozed", row["reason"])

    def test_push_gets_the_window_reason_as_why(self):
        push = WhyPush()
        self.run_once(push)
        self.assertEqual(len(push.calls), 1)
        self.assertEqual(push.calls[0]["why"], "wake event; anytime job and awake")

    def test_a_push_without_a_why_parameter_still_works(self):
        calls = []
        self.run_once(lambda title, body, once=None: calls.append(once) or "telegram")
        self.assertEqual(len(calls), 1)


class JobsCliQuiet(unittest.TestCase):
    """bin/limitless-jobs --send through the real bin/kevin-push and a fake hermes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        now = self.now = time.time()
        off = now - 0.1 * H
        write_rows(self.st / "sleepmode.jsonl", [{"at": iso(now - 12 * H), "on": True}, {"at": iso(now - 3 * H), "on": False},
                                                 {"at": iso(now - 1 * H), "on": True}, {"at": iso(off), "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": iso(now - 30), "ok": True}))
        write_rows(self.st / "unlocks.jsonl", [{"at": iso(now - 60)}])
        bindir = self.home / "bin"
        bindir.mkdir()
        hermes = bindir / "hermes"
        hermes.write_text("#!/bin/sh\nwhile [ $# -gt 0 ]; do if [ \"$1\" = --file ]; then cat \"$2\" >> \"$HOME/bodies\";"
                          " printf '\\n" + END + "\\n' >> \"$HOME/bodies\"; fi; shift; done\n")
        hermes.chmod(0o755)
        self.env = {"HOME": str(self.home), "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
                    "LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.home / "no-config.json"),
                    "LIMITLESS_SLEEPMODE": str(self.st / "sleepmode.jsonl"), "KEVIN_PUSH_BIN": str(KEVIN_PUSH),
                    "LIMITLESS_EXTERNAL_JOBS": "wake_brief"}

    def tearDown(self):
        self.tmp.cleanup()

    def jobs_cli(self):
        return subprocess.run([sys.executable, "-I", str(CLI), "--send"], env=self.env,
                              capture_output=True, text=True, timeout=30)

    def bodies(self):
        p = self.home / "bodies"
        return [b.strip("\n") for b in p.read_text().split(END + "\n") if b.strip()] if p.exists() else []

    def quiet(self, mode):
        (self.st / "quiet.json").write_text(json.dumps({"mode": mode, "since": iso(self.now - 2 * H)}))

    def test_off_drops_the_nap_message_and_it_stays_dropped(self):
        self.quiet("off")
        r = self.jobs_cli()
        self.assertIn("Back from nap: drop", r.stdout)
        self.assertIn("quiet: off until you reply on", r.stdout)
        self.assertEqual(self.bodies(), [])
        self.quiet("on")
        r = self.jobs_cli()
        self.assertIn("Back from nap: drop", r.stdout)
        self.assertEqual(self.bodies(), [], "a dropped event is never sent later")

    def test_a_delivery_ends_with_the_runner_reason(self):
        r = self.jobs_cli()
        self.assertIn("Back from nap: deliver", r.stdout)
        [body] = self.bodies()
        self.assertEqual(body.splitlines()[-1], "Why now: nap event; anytime job and awake")


if __name__ == "__main__":
    unittest.main()
