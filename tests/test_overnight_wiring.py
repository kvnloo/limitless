"""The overnight lines in the messages that already go out: one plan line in the MIQ job body at wind-down
(the MIQ question stays first) and one landed line in the wake brief (brief_post.finalize, called by
bin/limitless-brief). No dir configured adds nothing. Synthetic lane names only."""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import brief_post, jobs, jobs_runner  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0
MIQ_Q = "Your wind-down has started. Do you know the one thing that matters most tomorrow?"
CHOICES = "Reply: Yes / No / Later"   # one_tap: the MIQ is one tap, its choices line last
PLAN = "Overnight: a few tasks running, one queued"
WIND = "Screens down and lights low when you're ready."   # wind_down.DEFAULT, before the choices


def put(q: Path, sub: str, name: str, mtime: float):
    p = q / sub / f"{name}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("synthetic body that is never read\n")
    os.utime(p, (mtime, mtime))


class FakePush:
    def __init__(self):
        self.calls = []

    def __call__(self, title, body):
        self.calls.append((title, body))
        return "telegram"


class MiqBody(unittest.TestCase):
    def test_plan_line_follows_the_question(self):
        self.assertEqual(jobs_runner.body(jobs.MIQ, overnight=PLAN), f"{MIQ_Q}\n{PLAN}\n{CHOICES}")

    def test_no_plan_line_keeps_the_body(self):
        self.assertEqual(jobs_runner.body(jobs.MIQ), f"{MIQ_Q}\n{CHOICES}")
        self.assertEqual(jobs_runner.body(jobs.MIQ, overnight=""), f"{MIQ_Q}\n{CHOICES}")

    def test_other_jobs_never_get_the_line(self):
        self.assertNotIn("Overnight", jobs_runner.body(jobs.WAKE_BRIEF, overnight=PLAN))
        self.assertNotIn("Overnight", jobs_runner.body(jobs.NAP, overnight=PLAN))


class WindDownRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        att = self.root / "attention.json"
        att.write_text(json.dumps({"block": None, "resume": {"saved": NOW - 120}}))
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_GLIDE_ATTENTION": str(att)}
        (self.st / "sleepmode.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (
            {"at": NOW - 14 * H, "on": True}, {"at": NOW - 6 * H, "on": False})))
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
        (self.st / "unlocks.jsonl").write_text(json.dumps({"at": NOW - 120}) + "\n")
        (self.st / "events.jsonl").write_text(json.dumps({"event": "wind_down", "at": NOW - 60}) + "\n")

    def miq_body(self):
        push = FakePush()
        rows = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=self.env, home=self.root)
        self.assertEqual({r["job"]: r for r in rows}["MIQ for tonight?"]["action"], jobs.DELIVER, rows)
        return dict(push.calls)["MIQ for tonight?"]

    def test_wind_down_message_gets_the_plan_line(self):
        self.cfg.write_text(json.dumps({"work_queue_dir": "lanes"}))
        q = self.st / "lanes"
        for n in ("synthetic-alpha", "synthetic-beta"):
            put(q, "running", n, NOW - H)
        put(q, "queue", "synthetic-gamma", NOW - H)
        body = self.miq_body()
        self.assertEqual(body.splitlines(), [MIQ_Q, PLAN, WIND, CHOICES])
        self.assertNotIn("synthetic", body)

    def test_no_work_queue_configured_keeps_the_message(self):
        self.cfg.write_text("{}")
        self.assertEqual(self.miq_body(), f"{MIQ_Q}\n{WIND}\n{CHOICES}")


class Finalize(unittest.TestCase):
    def test_landed_line_is_the_last_line(self):
        out = brief_post.finalize("State: synthetic", None, NOW, saved=2,
                                  overnight="Overnight: a few done, one failed")
        self.assertEqual(out.splitlines(), ["State: synthetic", "Saved last night: 2 ideas",
                                            "Overnight: a few done, one failed"])

    def test_empty_landed_line_adds_nothing(self):
        self.assertEqual(brief_post.finalize("State: synthetic", None, NOW, overnight=""), "State: synthetic")


FAKE_LOOP = '''
import os
from pathlib import Path
def load_config():
    return {}
def build(cfg, day=None):
    return {"path": "/dev/null", "notif": "State: synthetic"}
def deliver(cfg, title, body, url=None, env=None):
    Path(os.environ["HOME"], "delivered.txt").write_text(body)
    return {"rc": 0, "shown": "telegram"}
'''


class BriefCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        lib = self.home / ".local/lib"
        lib.mkdir(parents=True)
        (lib / "limitless_loop.py").write_text(FAKE_LOOP)
        self.st = self.home / ".local/state/limitless"
        self.st.mkdir(parents=True)
        self.cfg = self.home / ".config/limitless/config.json"
        self.cfg.parent.mkdir(parents=True)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
        self.env["HOME"] = str(self.home)

    def send(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "bin" / "limitless-brief"), "send"], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return (self.home / "delivered.txt").read_text()

    def test_wake_brief_gets_one_landed_line(self):
        now = time.time()
        self.cfg.write_text(json.dumps({"work_queue_dir": "lanes"}))
        (self.st / "events.jsonl").write_text(json.dumps({"event": "wind_down", "at": now - 9 * H}) + "\n")
        q = self.st / "lanes"
        put(q, "done", "synthetic-alpha", now - 3 * H)
        put(q, "done", "synthetic-beta", now - 4 * H)
        put(q, "failed", "synthetic-gamma", now - 2 * H)
        put(q, "done", "synthetic-old", now - 30 * H)
        body = self.send()
        self.assertEqual(body.splitlines(), ["State: synthetic", "Overnight: a few done, one failed"])
        self.assertEqual(re.findall(r"\d", body.splitlines()[-1]), [])

    def test_no_work_queue_configured_adds_no_line(self):
        self.cfg.write_text("{}")
        self.assertEqual(self.send(), "State: synthetic")


if __name__ == "__main__":
    unittest.main()
