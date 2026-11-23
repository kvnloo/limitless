"""bin/kevin-push holds every delivered message to its shape (message_shape), with one content-free audit row
when anything was folded or cut. Fake `hermes` on PATH, temp HOME, synthetic text only."""
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
sys.path.insert(0, str(ROOT))
from limitless import message_shape, one_tap, tier_audit  # noqa: E402

MARKER = "zebra-marker-shape-text"
LONG = "\n".join(["Habit kept this week."] + [f"Line {w} {MARKER}." for w in "abcdefgh"]
                 + [one_tap.choices_line(("Keep", "Drop"))])


class Wired(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        fakebin = self.home / "fakebin"
        fakebin.mkdir()
        hermes = fakebin / "hermes"
        hermes.write_text("#!/bin/sh\nwhile [ $# -gt 0 ]; do [ \"$1\" = --file ] && cp \"$2\" \"$HOME/sent-body.txt\"; shift; done\n")
        hermes.chmod(hermes.stat().st_mode | stat.S_IEXEC)
        self.audit = self.home / "audit.jsonl"
        self.cfg = self.home / "config.json"
        self.env = dict(os.environ, HOME=str(self.home), PATH=f"{fakebin}:{os.environ['PATH']}",
                        LIMITLESS_SLEEPMODE=str(self.home / "none.jsonl"), LIMITLESS_STATE=str(self.home / "state"),
                        LIMITLESS_CONFIG=str(self.cfg), LIMITLESS_AUDIT=str(self.audit), CIRCADIAN_CLASS="decision")

    def push(self, body, title="Week review"):
        r = subprocess.run([sys.executable, "-I", str(CLI), "x", title, body], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def sent(self):
        return (self.home / "sent-body.txt").read_text()

    def rows(self):
        return [json.loads(ln) for ln in self.audit.read_text().splitlines()] if self.audit.exists() else []

    def test_a_long_message_goes_out_shaped(self):
        self.assertIn("telegram", self.push(LONG))
        lines = self.sent().splitlines()
        self.assertEqual(len(lines), 6)
        self.assertEqual(lines[0], "Habit kept this week.")
        self.assertEqual(lines[-2], "Reply: Keep / Drop")
        self.assertTrue(lines[-1].startswith("Why now: "))
        self.assertIn("and six more lines in the plugin", lines)

    def test_one_content_free_audit_row_when_folded(self):
        self.push(LONG)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["hook"], message_shape.AUDIT_HOOK)
        self.assertEqual((row["folded"], row["cut"]), (6, 0))
        self.assertNotIn(MARKER, self.audit.read_text())
        self.assertNotIn("Habit", self.audit.read_text())
        self.assertEqual(row["sha256"], "")

    def test_a_short_message_is_unchanged_and_writes_no_row(self):
        self.push("Pick one: keep the loop")
        self.assertEqual(self.sent(), "Pick one: keep the loop\nWhy now: you are awake and this fits any moment")
        self.assertEqual(self.rows(), [])

    def test_config_limits_are_used(self):
        self.cfg.write_text(json.dumps({"message_max_lines": 4}))
        self.push(LONG)
        self.assertEqual(len(self.sent().splitlines()), 4)

    def test_bad_config_limits_are_the_defaults(self):
        self.cfg.write_text(json.dumps({"message_max_lines": "lots", "message_max_line_chars": -1}))
        self.push(LONG)
        self.assertEqual(len(self.sent().splitlines()), 6)

    def test_a_long_line_is_cut_and_counted(self):
        self.push("Short TLDR\n" + "word " * 80)
        lines = self.sent().splitlines()
        self.assertLessEqual(len(lines[1]), 160)
        self.assertTrue(lines[1].endswith("…"))
        self.assertEqual((self.rows()[0]["folded"], self.rows()[0]["cut"]), (0, 1))

    def test_the_dedupe_key_is_the_unshaped_message(self):
        self.push(LONG)
        self.assertIn("duplicate", self.push(LONG))


class AuditRow(unittest.TestCase):
    def test_shape_event_is_counts_only(self):
        ev = tier_audit.shape_event(3, 1, now=1894708800.0)
        self.assertEqual(ev, {"at": "2030-01-15T12:00:00Z", "hook": "message_shape", "tier": "T1", "lines": 0,
                              "digits": 0, "opt_in": False, "sha256": "", "blocked": False, "folded": 3, "cut": 1})

    def test_shape_rows_are_not_injections(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "a.jsonl"
            env = {tier_audit.ENV_KEY: str(log)}
            self.assertTrue(tier_audit.record(tier_audit.shape_event(2, 0, now=1894708800.0), env=env, home=Path(d)))
            self.assertEqual(json.loads(log.read_text())["folded"], 2)
            self.assertEqual(tier_audit.check(log)["injections"], 0)


if __name__ == "__main__":
    unittest.main()
