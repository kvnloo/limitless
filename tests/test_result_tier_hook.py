"""The result_tier transform_tool_result hook: it replaces a listed health tool's numbers, fails open, and
records one content-free tier_audit row per replaced result (the glob and the count, never a value).
Made-up tool names and readings only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import result_tier as rt  # noqa: E402
from limitless import tier_audit  # noqa: E402

NOW = 1894708800.0
TOOL = "mcp__synthetic_health__get_night"
RESULT = json.dumps({"night": {"hr": 61, "hrv_ms": 47.5, "start": "2031-02-03T23:41:07Z"}, "id": 4521})
READINGS = ("61", "47", "2031", "23", "41", "4521")


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.audit = self.dir / "audit.jsonl"

    def fire(self, audit=True, tool=TOOL, result=RESULT, **cfg):
        cfg.setdefault("t0_tools", ["mcp__synthetic_health__*"])
        if audit:
            cfg["audit_path"] = str(self.audit)
        path = self.dir / "config.json"
        path.write_text(json.dumps(cfg))
        hook = rt.make_transform_tool_result(clock=lambda: NOW)
        with mock.patch.dict(os.environ, {"LIMITLESS_CONFIG": str(path)}, clear=True):
            return hook(tool_name=tool, args={"night": "2031-02-03"}, result=result, duration_ms=12, status="ok",
                        error_type=None, error_message=None, task_id="t", session_id="s", tool_call_id="c",
                        turn_id="u", api_request_id="r", conversation_id="v")

    def rows(self):
        if not self.audit.exists():
            return []
        return [json.loads(ln) for ln in self.audit.read_text().splitlines()]

    def test_a_listed_tool_gets_its_numbers_replaced(self):
        out = self.fire()
        self.assertEqual(json.loads(out), {"night": {"hr": "a number", "hrv_ms": "a number", "start": "a number"},
                                           "id": "a number"})

    def test_one_content_free_audit_row_per_replaced_result(self):
        self.fire()
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["hook"], tier_audit.RESULT_HOOK)
        self.assertEqual((row["glob"], row["replaced"]), ("mcp__synthetic_health__*", 4))
        self.assertEqual((row["tier"], row["digits"], row["blocked"], row["sha256"]), ("T1", 0, False, ""))
        line = self.audit.read_text()
        for v in READINGS:
            self.assertNotIn(v, line.replace(row["at"], ""))
        self.assertEqual(set(row), set(tier_audit.FIELDS) | {"glob", "replaced"})

    def test_the_weekly_check_does_not_count_filter_rows_as_injections(self):
        self.fire()
        self.assertEqual(tier_audit.check(self.audit), tier_audit._zero())

    def test_nothing_replaced_nothing_recorded(self):
        self.assertIsNone(self.fire(tool="mcp__other__get_night"))
        self.assertIsNone(self.fire(result="no reading yet"))
        self.assertIsNone(self.fire(raw_numbers_opt_in=True))
        self.assertEqual(self.rows(), [])

    def test_replaced_with_the_audit_off(self):
        self.assertIsInstance(self.fire(audit=False), str)
        self.assertFalse(self.audit.exists())

    def test_an_error_status_is_left_alone(self):
        hook = rt.make_transform_tool_result(clock=lambda: NOW)
        path = self.dir / "config.json"
        path.write_text(json.dumps({"t0_tools": ["*"]}))
        with mock.patch.dict(os.environ, {"LIMITLESS_CONFIG": str(path)}, clear=True):
            self.assertIsNone(hook(tool_name=TOOL, args={}, result="failed after 30 s", status="error",
                                   error_type="tool_error", error_message="failed after 30 s"))

    def test_malformed_calls_never_raise(self):
        hook = rt.make_transform_tool_result(clock=lambda: NOW)
        path = self.dir / "config.json"
        path.write_text(json.dumps({"t0_tools": ["*"], "audit_path": str(self.audit)}))
        with mock.patch.dict(os.environ, {"LIMITLESS_CONFIG": str(path)}, clear=True):
            for result in (b"hr 61", {"hr": 61}, None, 61):
                self.assertIsNone(hook(tool_name=TOOL, args=None, result=result))
            self.assertIsNone(hook())
            self.assertIsNone(hook(tool_name=None, result="hr 61"))
            with mock.patch.object(rt, "apply", side_effect=RuntimeError("boom")):
                self.assertIsNone(hook(tool_name=TOOL, result="hr 61"))
            with mock.patch.object(tier_audit, "record", side_effect=RuntimeError("boom")):
                self.assertEqual(hook(tool_name=TOOL, result="hr 61"), "hr a number")  # still replaced
        self.assertEqual(self.rows(), [])

    def test_a_broken_config_file_never_raises(self):
        path = self.dir / "config.json"
        path.write_text("{not json")
        hook = rt.make_transform_tool_result(clock=lambda: NOW)
        with mock.patch.dict(os.environ, {"LIMITLESS_CONFIG": str(path)}, clear=True):
            self.assertIsNone(hook(tool_name=TOOL, result="hr 61"))


class AuditRow(unittest.TestCase):
    def test_result_event_has_no_value_and_cleans(self):
        ev = tier_audit.result_event("fake_*", 3, now=NOW)
        self.assertEqual(tier_audit._clean(dict(ev, text="hr 61")), ev)
        self.assertEqual(ev["replaced"], 3)

    def test_bad_counts_are_zero(self):
        for bad in (-1, "3", True, None, 2.5):
            self.assertEqual(tier_audit.result_event("fake_*", bad, now=NOW)["replaced"], 0)


if __name__ == "__main__":
    unittest.main()
