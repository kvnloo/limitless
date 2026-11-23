"""The pre_llm_call card and every labeled tool result pass through tier_audit (synthetic fixtures only)."""
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from limitless import card, plugin, tier_audit, tools  # noqa: E402
from test_plugin import FakeCtx  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "state"
NOW = 1894708800.0
TODAY = date(2030, 1, 15)
MARKER = "zebra-marker-card-text"
CARD_DIGITS = f"[limitless] state card\nsleep short (proxy, 5 h) {MARKER}"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / "audit.jsonl"
        self.env = {tier_audit.ENV_KEY: str(self.log)}

    def rows(self):
        return [json.loads(ln) for ln in self.log.read_text().splitlines()] if self.log.exists() else []


class Gate(Base):
    def test_digits_without_opt_in_are_blocked_and_logged(self):
        self.assertIsNone(tier_audit.gate("pre_llm_call", CARD_DIGITS, False, env=self.env, now=NOW))
        (row,) = self.rows()
        self.assertEqual((row["tier"], row["opt_in"], row["blocked"]), ("T0", False, True))
        self.assertNotIn(MARKER, self.log.read_text())

    def test_digits_with_opt_in_pass_as_t0(self):
        self.assertEqual(tier_audit.gate("pre_llm_call", CARD_DIGITS, True, env=self.env, now=NOW), CARD_DIGITS)
        (row,) = self.rows()
        self.assertEqual((row["tier"], row["opt_in"], row["blocked"]), ("T0", True, False))

    def test_a_digit_card_is_blocked_even_with_the_audit_off(self):
        self.assertIsNone(tier_audit.gate("pre_llm_call", CARD_DIGITS, False, env={}, now=NOW))


class Hook(Base):
    def hook(self, extra=None):
        env = dict(self.env, LIMITLESS_STATE=str(FIX), **(extra or {}))
        return card.make_pre_llm_call(env=env, clock=lambda: NOW, today=lambda: TODAY)()

    def test_the_default_card_is_logged_t1_with_its_hash(self):
        out = self.hook()
        (row,) = self.rows()
        self.assertEqual((row["hook"], row["tier"], row["digits"], row["blocked"]), ("pre_llm_call", "T1", 0, False))
        self.assertEqual(row["sha256"], hashlib.sha256(out["context"].encode()).hexdigest())
        self.assertEqual(row["lines"], len(out["context"].splitlines()))

    def test_one_line_per_injection_even_from_the_cache(self):
        hook = card.make_pre_llm_call(env=dict(self.env, LIMITLESS_STATE=str(FIX)), clock=lambda: NOW,
                                      today=lambda: TODAY)
        hook(), hook()
        self.assertEqual(len(self.rows()), 2)

    def test_the_opt_in_card_is_logged_t0(self):
        out = self.hook({"LIMITLESS_RAW_IN_PROMPT": "1"})
        self.assertTrue(any(c.isdigit() for c in out["context"]))
        (row,) = self.rows()
        self.assertEqual((row["tier"], row["opt_in"], row["blocked"]), ("T0", True, False))

    def test_a_digit_card_without_opt_in_is_dropped_not_sent(self):
        with mock.patch.object(card.CardCache, "get", return_value=CARD_DIGITS):
            self.assertIsNone(self.hook())
        (row,) = self.rows()
        self.assertTrue(row["blocked"])
        self.assertNotIn(MARKER, self.log.read_text())


class ToolResults(Base):
    def setUp(self):
        super().setUp()
        self.ctx = FakeCtx()
        plugin.register(self.ctx)

    def call(self, name, extra=None):
        env = dict(self.env, LIMITLESS_STATE=str(FIX), **(extra or {}))
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(time, "time", return_value=NOW):
            return json.loads(self.ctx.tools[name]["handler"]({}, task_id="t", session_id="s"))

    def test_a_labeled_tool_result_is_logged(self):
        res = self.call("limitless_status")
        self.assertIn("label", res)
        (row,) = self.rows()
        self.assertEqual((row["hook"], row["tier"], row["blocked"]), ("tool:limitless_status", "T1", False))
        self.assertEqual(row["sha256"], hashlib.sha256(res["label"]["label"].encode()).hexdigest())

    def test_nested_labels_are_audited(self):
        self.call("limitless_window")
        (row,) = self.rows()
        self.assertEqual(row["hook"], "tool:limitless_window")
        self.assertGreaterEqual(row["lines"], 1)

    def test_a_result_without_a_label_is_not_logged(self):
        with mock.patch.dict(os.environ, dict(self.env, LIMITLESS_STATE="/definitely/not/here"), clear=True):
            res = json.loads(self.ctx.tools["limitless_status"]["handler"]({}))
        self.assertNotIn("label", res)
        self.assertEqual(self.rows(), [])

    def test_a_digit_label_without_opt_in_is_dropped_and_logged(self):
        bad = {"value": "x", "modality": "proxy", "age_h": 1.0, "evidence_tier": "indirect",
               "label": {"label": f"5 of 7 {MARKER}", "tier": "T1", "modality": "proxy"}}
        with mock.patch.object(tools, "labeled", return_value=bad):
            res = self.call("limitless_status")
        self.assertNotIn("label", res)
        self.assertNotIn(MARKER, json.dumps(res))
        (row,) = self.rows()
        self.assertEqual((row["tier"], row["blocked"]), ("T0", True))
        self.assertNotIn(MARKER, self.log.read_text())
        with mock.patch.object(tools, "labeled", return_value=bad):
            res = self.call("limitless_status", {"LIMITLESS_RAW_IN_PROMPT": "1"})
        self.assertIn(MARKER, res["label"]["label"])
        self.assertEqual((self.rows()[-1]["tier"], self.rows()[-1]["opt_in"]), ("T0", True))


if __name__ == "__main__":
    unittest.main()
