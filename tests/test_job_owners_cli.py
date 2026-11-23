"""bin/limitless-jobs and job owners, end to end: a fake limitless-brief on PATH and a fake kevin-push.

Nothing really sends: both senders are fakes in a temp HOME. Synthetic data only.
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

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-jobs"
H = 3600.0
OWN = "sent by its own sender"

FAKE_PUSH = """#!{py}
import json, os, sys
with open(os.environ["FAKE_PUSH_CALLS"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
print("kevin-push: telegram")
"""

# The real limitless-brief prints {"path", "notify_rc", "notify": {"shown", ...}, "notif_text"} and exits 0.
FAKE_BRIEF = """#!{py}
import json, os, sys
with open(os.environ["FAKE_BRIEF_CALLS"], "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "once": os.environ.get("KEVIN_PUSH_ONCE")}}) + "\\n")
shown = os.environ.get("FAKE_BRIEF_SHOWN", "telegram")
print(json.dumps({{"path": "/dev/null", "notify_rc": 0 if shown == "telegram" else 1,
                  "notify": {{"shown": shown}}, "notif_text": "synthetic brief"}}, indent=1))
sys.exit(int(os.environ.get("FAKE_BRIEF_EXIT", "0")))
"""


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class JobOwnersCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        now = time.time()
        write_rows(self.st / "sleepmode.jsonl", [{"at": iso(now - 8.5 * H), "on": True},
                                                 {"at": iso(now - 0.2 * H), "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": iso(now - 30), "ok": True}))
        write_rows(self.st / "unlocks.jsonl", [{"at": iso(now - 60)}])
        bindir = self.home / "bin"
        bindir.mkdir()
        for name, text in (("kevin-push", FAKE_PUSH), ("limitless-brief", FAKE_BRIEF)):
            p = bindir / name
            p.write_text(text.format(py=sys.executable))
            p.chmod(0o755)
        self.push_log, self.brief_log = self.home / "push-calls.jsonl", self.home / "brief-calls.jsonl"
        self.env = {"HOME": str(self.home), "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
                    "LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.home / "no-config.json"),
                    "FAKE_PUSH_CALLS": str(self.push_log), "FAKE_BRIEF_CALLS": str(self.brief_log),
                    "KEVIN_PUSH_ONCE": "left:in-the-env"}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, **env):
        r = subprocess.run([sys.executable, "-I", str(CLI), *args], env=dict(self.env, **env),
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    @staticmethod
    def rows(p):
        return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []

    def sent(self):
        return self.rows(self.st / "jobs-sent.jsonl")

    def line(self, r, job):
        return next(ln for ln in r.stdout.splitlines() if ln.startswith(job + ":"))

    def test_send_runs_limitless_brief_not_the_placeholder(self):
        r = self.run_cli("--send")
        self.assertEqual([c["argv"] for c in self.rows(self.brief_log)], [["send"]], r.stdout)
        self.assertIsNone(self.rows(self.brief_log)[0]["once"], "limitless-brief finds its own key")
        self.assertEqual(self.rows(self.push_log), [], "no placeholder through kevin-push")
        self.assertTrue(self.line(r, "Wake-up brief").startswith("Wake-up brief: deliver"))
        self.assertEqual(len(self.sent()), 1)
        r2 = self.run_cli("--send")
        self.assertEqual(len(self.rows(self.brief_log)), 1, r2.stdout)
        self.assertIn("Wake-up brief: drop", r2.stdout)

    def test_failing_limitless_brief_sends_nothing(self):
        for env in ({"FAKE_BRIEF_EXIT": "1"}, {"FAKE_BRIEF_SHOWN": "log (telegram rc=1)"}):
            r = self.run_cli("--send", **env)
            self.assertEqual(self.rows(self.push_log), [], env)
            self.assertEqual(self.sent(), [], env)
            line = self.line(r, "Wake-up brief")
            self.assertTrue(line.startswith("Wake-up brief: hold"), line)
            self.assertIn("limitless-brief", line)
            self.assertIn("limitless-brief", r.stderr, "the failure is logged")

    def test_missing_limitless_brief_sends_nothing(self):
        r = self.run_cli("--send", LIMITLESS_BRIEF_BIN=str(self.home / "nope"))
        self.assertEqual(self.rows(self.push_log), [])
        self.assertEqual(self.rows(self.brief_log), [])
        self.assertEqual(self.sent(), [])
        line = self.line(r, "Wake-up brief")
        self.assertTrue(line.startswith("Wake-up brief: hold"), line)
        self.assertIn("limitless-brief did not run", line)

    def test_external_wake_brief_is_left_to_its_sender(self):
        r = self.run_cli("--send", LIMITLESS_EXTERNAL_JOBS="wake_brief")
        self.assertEqual(self.rows(self.brief_log), [])
        self.assertEqual(self.rows(self.push_log), [])
        self.assertEqual(self.sent(), [])
        self.assertIn(OWN, self.line(r, "Wake-up brief"))

    def test_dry_run_with_external_jobs_in_config_shows_both_rows(self):
        cfg = self.home / "config.json"
        cfg.write_text(json.dumps({"external_jobs": ["wake_brief", "nap"]}))
        r = self.run_cli(LIMITLESS_CONFIG=str(cfg))
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 4, r.stdout)
        self.assertTrue(self.line(r, "Wake-up brief").startswith("Wake-up brief: deliver"), r.stdout)
        self.assertIn(OWN, self.line(r, "Wake-up brief"))
        self.assertIn(OWN, self.line(r, "Back from nap"))
        self.assertEqual(sum(OWN in ln for ln in lines), 2, r.stdout)
        self.assertEqual(self.rows(self.push_log), [])
        self.assertEqual(self.rows(self.brief_log), [])
        self.assertEqual(self.sent(), [])


if __name__ == "__main__":
    unittest.main()
