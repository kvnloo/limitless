"""tier_audit: one content-free JSON line per injection, proving which privacy tier the model saw.

Synthetic cards only: the marker string below stands in for card text and must never reach the log.
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from limitless import tier_audit  # noqa: E402

MARKER = "zebra-marker-card-text"
CARD_T1 = f"[limitless] state card\nwindow: peak ({MARKER})\nsleep short (proxy)"
CARD_DIGITS = f"[limitless] state card\nsleep short (proxy, 5 h) {MARKER}"
NOW = 1894708800.0


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / "audit.jsonl"
        self.env = {tier_audit.ENV_KEY: str(self.log)}
        self.home = Path(self.tmp.name) / "home"

    def rows(self):
        return [json.loads(ln) for ln in self.log.read_text().splitlines()]


class Record(Base):
    def test_one_line_per_record_with_the_documented_fields(self):
        for _ in range(2):
            self.assertTrue(tier_audit.record(tier_audit.event("pre_llm_call", CARD_T1, False, now=NOW),
                                              env=self.env, home=self.home))
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows[0]), {"at", "hook", "tier", "lines", "digits", "opt_in", "sha256", "blocked"})
        self.assertEqual(rows[0]["hook"], "pre_llm_call")
        self.assertEqual(rows[0]["tier"], "T1")
        self.assertEqual(rows[0]["lines"], 3)
        self.assertEqual(rows[0]["digits"], 0)
        self.assertIs(rows[0]["opt_in"], False)
        self.assertIs(rows[0]["blocked"], False)
        self.assertEqual(len(rows[0]["sha256"]), 64)
        self.assertTrue(rows[0]["at"].endswith("Z"))

    def test_the_card_text_is_never_written(self):
        ev = dict(tier_audit.event("pre_llm_call", CARD_DIGITS, True, now=NOW), text=CARD_DIGITS)
        tier_audit.record(ev, env=self.env, home=self.home)
        raw = self.log.read_text()
        self.assertNotIn(MARKER, raw)
        self.assertNotIn("text", json.loads(raw))

    def test_file_is_created_0600_and_only_appended(self):
        tier_audit.record(tier_audit.event("pre_llm_call", CARD_T1, False, now=NOW), env=self.env, home=self.home)
        self.assertEqual(stat.S_IMODE(os.stat(self.log).st_mode), 0o600)
        first = self.log.read_text()
        tier_audit.record(tier_audit.event("pre_llm_call", CARD_T1, False, now=NOW), env=self.env, home=self.home)
        self.assertTrue(self.log.read_text().startswith(first))

    def test_off_when_no_path_is_configured(self):
        self.assertIsNone(tier_audit.audit_path({}, self.home))
        self.assertFalse(tier_audit.record(tier_audit.event("pre_llm_call", CARD_T1, False, now=NOW),
                                           env={}, home=self.home))

    def test_config_audit_path(self):
        cfg = Path(self.tmp.name) / "config.json"
        cfg.write_text(json.dumps({"audit_path": str(self.log)}))
        env = {"LIMITLESS_CONFIG": str(cfg)}
        self.assertEqual(tier_audit.audit_path(env, self.home), self.log)
        tier_audit.record(tier_audit.event("pre_llm_call", CARD_T1, False, now=NOW), env=env, home=self.home)
        self.assertEqual(len(self.rows()), 1)

    def test_never_raises(self):
        env = {tier_audit.ENV_KEY: str(Path(self.tmp.name) / "no" / "such" / "dir" / "a.jsonl")}
        self.assertFalse(tier_audit.record(tier_audit.event("pre_llm_call", CARD_T1, False, now=NOW), env=env))
        self.assertFalse(tier_audit.record(None, env=self.env, home=self.home))
        self.assertFalse(tier_audit.record({"tier": object()}, env=self.env, home=self.home))


if __name__ == "__main__":
    unittest.main()
