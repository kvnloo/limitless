"""limitless/call_brief.py: the digit-free state card as a brief file a voice call opens with.

Synthetic fixtures only (tests/fixtures/state, fixture clock 2030-01-15T12:00:00Z). Nothing sends.
"""
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import call_brief  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
NOW = 1894708800.0
TODAY = date(2030, 1, 15)
H = 3600.0


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        shutil.copytree(FIX, self.st)
        self.reader = StateReader(self.st)
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.dir / "none.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, **kw):
        return call_brief.render(self.reader, NOW, TODAY, env=self.env, **kw)


class Content(Base):
    def test_tldr_first_then_at_most_three_lines(self):
        lines = self.render()["lines"]
        self.assertTrue(lines[0].startswith("TLDR: "), lines)
        self.assertLessEqual(len(lines), 4)

    def test_tldr_says_the_window_class_and_the_asks(self):
        self.assertEqual(self.render()["lines"][0], "TLDR: peak window; asks waiting")

    def test_body_is_the_card_labels(self):
        self.assertEqual(self.render()["lines"][1:], [
            "sleep short (proxy); readiness low (imported)",
            "habit this week: Lights down when wind-down starts; today Done",
            "not recording: anki, bike, scale"])

    def test_no_digit_no_card_id(self):
        h = self.st / "habit.json"
        h.write_text(h.read_text().replace("Lights down", "t_510c250d Lights down 3"))
        body = self.render()["body"]
        self.assertFalse(re.search(r"\d", body), body)
        self.assertNotIn("t_", body)

    def test_lines_are_short(self):
        h = self.st / "habit.json"
        h.write_text(h.read_text().replace("Lights down", "Lights down " + "very " * 60))
        self.assertTrue(all(len(ln) <= call_brief.LINE_MAX for ln in self.render()["lines"]))

    def test_asks_label_from_the_configured_queue(self):
        q = self.dir / "asks.jsonl"
        q.write_text('{"id": "a1", "kind": "decision", "title": "Pick a bike slot", "at": "2030-01-15T08:00:00Z"}\n')
        self.env["LIMITLESS_ASKS"] = str(q)
        tldr = self.render()["lines"][0]
        self.assertEqual(tldr, "TLDR: peak window; one decision ready")
        self.assertNotIn("bike slot", self.render()["body"])

    def test_unknown_window_says_so(self):
        (self.st / "sleepmode.jsonl").unlink()
        self.assertTrue(self.render()["lines"][0].startswith("TLDR: window unknown"))

    def test_text_has_a_generated_header_comment(self):
        text = call_brief.text(self.render()["body"], NOW)
        self.assertEqual(text.splitlines()[0], "<!-- limitless call brief; generated: 2030-01-15T12:00:00Z -->")
        self.assertEqual(text.splitlines()[1:], self.render()["lines"])


class WriteBase(Base):
    def setUp(self):
        super().setUp()
        self.out = self.dir / "briefs" / "latest.md"
        self.out.parent.mkdir()

    def write(self, out=None):
        return call_brief.write(self.out if out is None else out, NOW, TODAY, env=self.env)


class Write(WriteBase):

    def test_writes_the_text_atomically_mode_0600(self):
        code, why = self.write()
        self.assertEqual((code, why), (0, "call brief written"))
        self.assertEqual(self.out.read_text(), call_brief.text(self.render()["body"], NOW))
        self.assertEqual(stat.S_IMODE(self.out.stat().st_mode), 0o600)
        self.assertEqual([p.name for p in self.out.parent.iterdir()], ["latest.md"])

    def test_a_digit_is_refused_exit_2_and_nothing_written(self):
        self.out.write_text("old\n")
        digit = {"text": "x", "lines": ["habit this week: walk 3 km"], "items": {"window": {"value": "peak"}}}
        with mock.patch.object(call_brief.card, "build", return_value=digit):
            code, why = self.write()
        self.assertEqual(code, 2)
        self.assertIn("refused", why)
        self.assertNotRegex(why, r"\d")
        self.assertEqual(self.out.read_text(), "old\n")
        self.assertEqual([p.name for p in self.out.parent.iterdir()], ["latest.md"])

    def test_the_gate_is_audited_under_its_hook_without_opt_in(self):
        self.env["LIMITLESS_AUDIT"] = str(self.dir / "audit.jsonl")
        self.write()
        row = (self.dir / "audit.jsonl").read_text()
        self.assertIn('"hook": "call_brief"', row)
        self.assertIn('"opt_in": false', row)

    def test_never_raises(self):
        with mock.patch.object(call_brief.card, "build", side_effect=RuntimeError("boom 42")):
            code, why = self.write()
        self.assertEqual(code, 1)
        self.assertEqual(len(why.splitlines()), 1)
        self.assertNotIn("42", why)

    def test_unwritable_target_is_exit_1_one_line(self):
        code, why = self.write(self.dir / "missing-dir" / "latest.md")
        self.assertEqual(code, 1)
        self.assertEqual(len(why.splitlines()), 1)
        self.assertFalse((self.dir / "missing-dir").exists())

    def test_no_state_dir_writes_nothing(self):
        shutil.rmtree(self.st)
        code, why = self.write()
        self.assertEqual(code, 0)
        self.assertIn("nothing written", why)
        self.assertFalse(self.out.exists())


class Idempotent(WriteBase):
    def test_same_content_later_leaves_the_file_untouched(self):
        self.assertEqual(self.write()[0], 0)
        os.utime(self.out, ns=(1_000_000_000, 1_000_000_000))
        before = self.out.read_text()
        code, why = call_brief.write(self.out, NOW + 600, TODAY, env=self.env)
        self.assertEqual((code, why), (0, "call brief unchanged"))
        self.assertEqual(self.out.stat().st_mtime_ns, 1_000_000_000)
        self.assertEqual(self.out.read_text(), before)

    def test_changed_content_is_rewritten_with_a_new_stamp(self):
        self.write()
        (self.st / "inputs.json").unlink()
        code, why = call_brief.write(self.out, NOW + 600, TODAY, env=self.env)
        self.assertEqual((code, why), (0, "call brief written"))
        self.assertIn("2030-01-15T12:10:00Z", self.out.read_text().splitlines()[0])
        self.assertNotIn("not recording", self.out.read_text())

    def test_a_file_without_our_header_is_replaced(self):
        self.out.write_text(self.render()["body"] + "\n")
        self.assertEqual(self.write(), (0, "call brief written"))
        self.assertTrue(self.out.read_text().startswith("<!-- limitless call brief"))


class Config(Base):
    def config(self, cfg):
        p = self.dir / "config.json"
        p.write_text(json.dumps(cfg))
        self.env["LIMITLESS_CONFIG"] = str(p)

    def test_nothing_configured_and_no_out_is_exit_0_not_configured(self):
        self.assertEqual(call_brief.write(None, NOW, TODAY, env=self.env), (0, "not configured"))
        self.assertEqual(call_brief.out_path(None, self.env), None)

    def test_relative_path_is_in_the_state_dir(self):
        self.config({"call_brief_file": "call-brief.md"})
        self.assertEqual(call_brief.out_path(None, self.env), self.st / "call-brief.md")
        self.assertEqual(call_brief.write(None, NOW, TODAY, env=self.env), (0, "call brief written"))
        self.assertTrue((self.st / "call-brief.md").is_file())

    def test_absolute_path_is_used_as_is(self):
        self.config({"call_brief_file": str(self.dir / "latest.md")})
        self.assertEqual(call_brief.out_path(None, self.env), self.dir / "latest.md")

    def test_out_flag_wins_over_config(self):
        self.config({"call_brief_file": "call-brief.md"})
        self.assertEqual(call_brief.out_path(str(self.dir / "x.md"), self.env), self.dir / "x.md")

    def test_blank_or_non_string_is_not_configured(self):
        for v in ("", "  ", 7, None, ["a"]):
            self.config({"call_brief_file": v})
            self.assertEqual(call_brief.out_path(None, self.env), None, v)


if __name__ == "__main__":
    unittest.main()
