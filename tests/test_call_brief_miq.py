"""limitless/call_brief.py: with an MIQ open and voice_miq on, the call brief ends with one line asking it.

Synthetic fixtures only (tests/fixtures/state, fixture clock 2030-01-15T12:00:00Z). Nothing sends.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import call_brief, jobs, jobs_runner, voice_miq  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
NOW = 1894708800.0
TODAY = date(2030, 1, 15)
LINE = "Ask once: " + jobs_runner.MIQ_QUESTION


class MiqLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        shutil.copytree(FIX, self.st)
        self.cfg = self.dir / "config.json"
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.cfg)}
        self.plain = self.render()

    def tearDown(self):
        self.tmp.cleanup()

    def render(self):
        return call_brief.render(StateReader(self.st), NOW, TODAY, env=self.env)["lines"]

    def on(self, mode="dry_run"):
        self.cfg.write_text(json.dumps({"voice_miq": mode}))

    def sent(self, t):
        with open(self.st / jobs_runner.SENT_LOG, "a") as f:
            f.write(json.dumps({"t": t, "k": "k-test", "job": "miq"}) + "\n")

    def test_the_line_is_plain_short_and_digit_free(self):
        self.assertLessEqual(len(LINE), call_brief.LINE_MAX)
        self.assertIsNone(re.search(r"\d", LINE))

    def test_open_miq_ends_the_brief_with_one_line_asking_it(self):
        for mode in ("dry_run", "write"):
            self.on(mode)
            self.sent(NOW - 1800)
            lines = self.render()
            self.assertEqual(lines, self.plain + [LINE], mode)
            self.assertEqual(sum(1 for ln in lines if jobs_runner.MIQ_QUESTION in ln), 1)

    def test_no_miq_sent_no_line(self):
        self.on()
        self.assertEqual(self.render(), self.plain)

    def test_voice_miq_off_no_line(self):
        self.sent(NOW - 1800)
        self.assertEqual(self.render(), self.plain)

    def test_stale_miq_no_line(self):
        self.on()
        self.sent(NOW - jobs.MIQ_STALE_S - 1)
        self.assertEqual(self.render(), self.plain)

    def test_captured_miq_no_line(self):
        self.on()
        self.sent(NOW - 1800)
        (self.st / voice_miq.MARK).write_text(json.dumps({"miq_sent_at": NOW - 1800, "captured_at": NOW - 60}))
        self.assertEqual(self.render(), self.plain)

    def test_written_file_ends_with_the_line_and_passes_the_gate(self):
        self.on()
        self.sent(NOW - 1800)
        out = self.dir / "latest.md"
        self.assertEqual(call_brief.write(out, NOW, TODAY, env=self.env), (0, "call brief written"))
        self.assertEqual(out.read_text().splitlines()[-1], LINE)


if __name__ == "__main__":
    unittest.main()
