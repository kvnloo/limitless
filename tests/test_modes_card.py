"""Attention modes on the pre_llm_call card: one digit-free line, still through tier_audit.gate. Synthetic only."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card, modes, tier_audit  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "state"
NOW = 2_000_000_000.0


class ModeLines(unittest.TestCase):
    def test_each_mode_has_one_short_digit_free_line(self):
        self.assertEqual(modes.line("focused"), "focused mode: answer briefly, hold non-urgent asks")
        self.assertEqual(modes.line("brainstorm"), "brainstorm mode: offer options, defer decisions")
        self.assertEqual(modes.line("pm"), "pm mode: status, blockers, next step")
        self.assertEqual(modes.line("copilot"), "copilot mode: do the step, report the result")
        for m in modes.MODES:
            ln = modes.line(m)
            self.assertFalse(any(c.isdigit() for c in ln), ln)
            self.assertNotIn("\n", ln)
            self.assertLessEqual(len(ln), 60)
            self.assertTrue(ln.startswith(m + " mode: "))

    def test_none_and_unknown_have_no_line(self):
        for m in ("none", "off", "sprint", None, ""):
            self.assertIsNone(modes.line(m))


class CardHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name) / "state"
        shutil.copytree(FIX, self.st)
        self.audit = Path(self.tmp.name) / "audit.jsonl"
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(Path(self.tmp.name) / "none.json"),
                    "LIMITLESS_AUDIT": str(self.audit)}
        self.hook = card.make_pre_llm_call(env=self.env, clock=lambda: NOW, today=lambda: date(2033, 5, 18))

    def ctx(self):
        out = self.hook(session_id="s", user_message="hi", conversation_history=[], is_first_turn=True)
        return out["context"]

    def test_no_mode_is_the_card_as_before(self):
        before = self.ctx()
        self.assertFalse(any(" mode: " in ln for ln in before.splitlines()))
        self.assertFalse((self.st / "mode.json").exists())

    def test_each_mode_adds_its_line_last(self):
        base = self.ctx()
        for m in modes.MODES:
            modes.save(self.st, m)
            text = self.ctx()
            self.assertEqual(text, base + "\n" + modes.line(m))

    def test_off_removes_the_line_again(self):
        base = self.ctx()
        modes.save(self.st, "pm")
        self.assertNotEqual(self.ctx(), base)
        modes.save(self.st, "off")
        self.assertEqual(self.ctx(), base)

    def test_a_broken_mode_file_is_the_card_as_before(self):
        base = self.ctx()
        (self.st / "mode.json").write_text("{not json")
        self.assertEqual(self.ctx(), base)

    def test_the_card_with_a_mode_passes_the_gate_and_is_audited_t1(self):
        modes.save(self.st, "focused")
        text = self.ctx()
        self.assertEqual(tier_audit.gate("test", text, False), text)
        rows = [json.loads(ln) for ln in self.audit.read_text().splitlines()]
        self.assertEqual(rows[-1]["tier"], "T1")
        self.assertFalse(rows[-1]["blocked"])
        self.assertEqual(rows[-1]["lines"], len(text.splitlines()))


if __name__ == "__main__":
    unittest.main()
