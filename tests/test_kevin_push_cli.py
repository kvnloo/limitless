"""bin/kevin-push end to end with a fake `hermes` on PATH and a temp HOME. Synthetic data only."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "kevin-push"


class KevinPushCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        fakebin = self.home / "fakebin"
        fakebin.mkdir()
        hermes = fakebin / "hermes"
        # records the file it was asked to send
        hermes.write_text("#!/bin/sh\nwhile [ $# -gt 0 ]; do [ \"$1\" = --file ] && cp \"$2\" \"$HOME/sent-body.txt\"; shift; done\n")
        hermes.chmod(hermes.stat().st_mode | stat.S_IEXEC)
        self.env = dict(os.environ, HOME=str(self.home), PATH=f"{fakebin}:{os.environ['PATH']}",
                        LIMITLESS_SLEEPMODE=str(self.home / "none.jsonl"))
        self.st = self.home / ".local/state/kevin-push"

    def tearDown(self):
        self.tmp.cleanup()

    def push(self, tag, title, body, cls="decision", strict=False):
        env = dict(self.env, CIRCADIAN_CLASS=cls)
        if strict:
            env["KEVIN_PUSH_STRICT"] = "1"
        return subprocess.run([sys.executable, "-I", str(CLI), tag, title, body], env=env,
                              capture_output=True, text=True, timeout=30)

    def last_log(self):
        return json.loads((self.st / "log.jsonl").read_text().splitlines()[-1])

    def test_decision_is_sent_without_card_ids(self):
        r = self.push("x", "Pick one", "Decision: t_510c250d: keep the loop")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.last_log()["how"], "telegram")
        self.assertEqual((self.home / "sent-body.txt").read_text(), "Decision: keep the loop")

    def test_asks_digest_is_folded_and_saved_for_the_brief(self):
        r = self.push("asks", "Asks waiting on you", "A1: one\nA2: two\nA3: three")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.last_log()["how"], "folded (brief line)")
        self.assertFalse((self.home / "sent-body.txt").exists())
        asks = json.loads((self.st / "asks-latest.json").read_text())
        self.assertEqual(asks["count"], 3)

    def test_strict_mode_exits_3_when_not_delivered(self):
        r = self.push("x", "Note", "fyi", cls="report", strict=True)
        self.assertEqual(r.returncode, 3)

    def test_strict_mode_exits_0_when_delivered(self):
        r = self.push("x", "Pick", "now", strict=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
