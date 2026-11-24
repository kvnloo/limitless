"""bin/limitless-jobs --send end to end for the sender confirmation, with a fake kevin-push on PATH (never the
real one) that records each call, appends its row to the push log like the real one, and can be made to succeed,
fail or hold. The doctor row then reads the confirmation's own result from that log. Synthetic state in a temp
HOME; env passed explicitly through child_env.""" 
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
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
CLI = ROOT / "bin" / "limitless-jobs"
sys.path.insert(0, str(ROOT))
from limitless import doctor  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

H = 3600
PROFILE = "backup-bot"

# Records each call and, like the real one, appends its row to the push log (how from FAKE_PUSH_HOW).
FAKE_PUSH = """#!{py}
import json, os, sys, time
with open(os.environ["FAKE_PUSH_CALLS"], "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "strict": os.environ.get("KEVIN_PUSH_STRICT"),
                        "cls": os.environ.get("CIRCADIAN_CLASS")}}) + "\\n")
how = os.environ.get("FAKE_PUSH_HOW", "telegram")
with open(os.environ["FAKE_PUSH_LOG"], "a") as f:
    f.write(json.dumps({{"at": int(time.time()), "tag": sys.argv[1], "cls": "decision", "title": sys.argv[2],
                        "body": sys.argv[3], "how": how}}) + "\\n")
print("kevin-push: " + how)
sys.exit(0 if how == "telegram" or os.environ.get("KEVIN_PUSH_STRICT") != "1" else 3)
"""


def row(at, title, how):
    return {"at": int(at), "tag": "limitless", "cls": "decision", "title": title, "how": how,
            "body": "Private body words.\nWhy now: a reason"}


class SenderConfirmCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        bindir = self.home / "bin"
        bindir.mkdir()
        fake = bindir / "kevin-push"
        fake.write_text(FAKE_PUSH.format(py=sys.executable))
        fake.chmod(0o755)
        self.calls = self.home / "calls.jsonl"
        self.log = self.st / "push-log.jsonl"
        self.cfg = {"sender_confirm": "write", "push_log": "push-log.jsonl"}
        (self.home / "config.json").write_text(json.dumps(self.cfg))
        self.env = {"HOME": str(self.home), "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
                    "LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.home / "config.json"),
                    "FAKE_PUSH_CALLS": str(self.calls), "FAKE_PUSH_LOG": str(self.log)}
        self.at = int(time.time()) - 120
        (self.st / "push-sender.json").write_text(json.dumps({"profile": PROFILE, "at": self.at}))

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, **kw):
        self.cfg.update(kw)
        (self.home / "config.json").write_text(json.dumps(self.cfg))

    def run_cli(self, *args, **env):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(dict(self.env, **env)),
                              capture_output=True, text=True, timeout=60)

    def calls_made(self):
        return [json.loads(ln) for ln in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def line(self, out, name="Sender confirm"):
        return [ln for ln in out.splitlines() if ln.startswith(name + ": ")]

    def doctor_reason(self):
        r = doctor.sender_confirm_row(StateReader(self.st), self.cfg, time.time(), env={})
        return r["status"], doctor.words(r["reason"])

    def test_success_sends_one_plain_confirmation_once_and_the_doctor_says_it_reached_you(self):
        r = self.run_cli("--send")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.line(r.stdout),
                         ["Sender confirm: deliver: your reply changed the sender for your phone pushes; sent"])
        calls = self.calls_made()
        self.assertEqual(len(calls), 1)
        argv = calls[0]["argv"]
        self.assertEqual(argv[:3], ["limitless", "Pushes",
                                    "This is the new route for your phone pushes. If you see this, it works."])
        self.assertEqual(argv[argv.index("--once") + 1], f"sender_confirm:{self.at}")
        self.assertEqual(argv[argv.index("--why") + 1], "your reply changed the sender for your phone pushes")
        self.assertEqual((calls[0]["strict"], calls[0]["cls"]), ("1", "decision"))   # the normal send gate
        self.assertIsNone(re.search(r"\d", argv[2]))
        self.assertNotIn(PROFILE, " ".join(argv[:3]) + r.stdout)
        status, said = self.doctor_reason()
        self.assertEqual(status, doctor.LIVE)
        self.assertIn("the new sender reached you", said)
        r = self.run_cli("--send")                                   # a replay never sends twice
        self.assertEqual(self.line(r.stdout),
                         ["Sender confirm: drop: this sender change was already confirmed"])
        self.assertEqual(len(self.calls_made()), 1)

    def test_a_failed_send_is_the_proof_the_new_sender_did_not_reach_you(self):
        r = self.run_cli("--send", FAKE_PUSH_HOW="log (telegram rc=1)")
        self.assertEqual(self.line(r.stdout),
                         ["Sender confirm: hold: your reply changed the sender for your phone pushes; the new sender "
                          "did not reach you: the send failed; the next pass tries again"])
        status, said = self.doctor_reason()
        self.assertEqual(status, doctor.MISSING)
        self.assertIn("the new sender did not reach you", said)

    def test_a_sleep_mode_hold_waits(self):
        r = self.run_cli("--send", FAKE_PUSH_HOW="held (sleep mode)")
        self.assertEqual(self.line(r.stdout),
                         ["Sender confirm: hold: your reply changed the sender for your phone pushes; not delivered: "
                          "Sleep mode holds it; the next pass tries again"])
        status, said = self.doctor_reason()
        self.assertEqual(status, doctor.LIVE)
        self.assertIn("waits", said)
        r = self.run_cli("--send")                                   # awake again: the next pass sends it
        self.assertIn("; sent", self.line(r.stdout)[0])
        self.assertEqual(len(self.calls_made()), 2)

    def test_a_dry_run_says_what_it_would_send_and_writes_nothing(self):
        r = self.run_cli()
        self.assertEqual(self.line(r.stdout), [
            'Sender confirm: deliver: your reply changed the sender for your phone pushes; would send "Pushes": '
            '"This is the new route for your phone pushes. If you see this, it works." (dry run of limitless-jobs): '
            'nothing sent'])
        self.assertEqual(self.calls_made(), [])
        self.assertFalse((self.st / "sender-confirm.json").exists())

    def test_with_the_outage_recap_due_too_the_confirmation_goes_first_and_the_recap_waits_a_pass(self):
        now = time.time()
        self.config(outage_recap="write")
        self.log.write_text("".join(json.dumps(r) + "\n" for r in (
            row(now - 5 * H, "Wake-up brief", "log (telegram rc=1)"),
            row(now - 4 * H, "MIQ for tonight?", "log (no sender profile)"),
            row(now - 600, "Habit check-in", "telegram"))))
        r = self.run_cli("--send")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c["argv"][1] for c in self.calls_made()], ["Pushes"])
        self.assertIn("; sent", self.line(r.stdout)[0])
        recap = self.line(r.stdout, "Outage recap")
        self.assertEqual(len(recap), 1)
        self.assertTrue(recap[0].startswith("Outage recap: hold: pushes came back after an outage; waits for the "
                                            "next pass"), recap)
        self.assertFalse((self.st / "outage-recap.json").exists())
        r = self.run_cli("--send")
        self.assertEqual([c["argv"][1] for c in self.calls_made()], ["Pushes", "Pushes are back"])
        self.assertEqual(self.line(r.stdout, "Outage recap"),
                         ["Outage recap: deliver: pushes came back after an outage; sent"])


if __name__ == "__main__":
    unittest.main()
