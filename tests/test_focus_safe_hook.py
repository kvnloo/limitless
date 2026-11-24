"""The focus_safe pre_tool_call hook: advisory only. It never blocks, never rewrites args and fails open; on a
warn it records one content-free tier_audit line. Synthetic serials and display ids only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import focus_safe as fs  # noqa: E402

NOW = 1894708800.0
OWNER = "SYNTHETIC0001"
TAP = {"command": f"adb -s {OWNER} shell input tap 5 5"}


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.audit = self.dir / "audit.jsonl"

    def env(self, **cfg):
        path = self.dir / "config.json"
        path.write_text(json.dumps(dict({"audit_path": str(self.audit)}, **cfg)))
        return {"LIMITLESS_CONFIG": str(path)}

    def fire(self, env, tool="terminal", args=None):
        args = dict(TAP) if args is None else args
        before = json.dumps(args, sort_keys=True)
        hook = fs.make_pre_tool_call(clock=lambda: NOW)
        with mock.patch.dict(os.environ, env, clear=True):
            out = hook(tool_name=tool, args=args, task_id="t", session_id="s", tool_call_id="c", turn_id="u")
        self.assertIsNone(out)  # never a block, approve or modify directive
        self.assertEqual(json.dumps(args, sort_keys=True), before)  # args never rewritten
        return out

    def rows(self):
        return [json.loads(ln) for ln in self.audit.read_text().splitlines()] if self.audit.exists() else []

    def test_off_by_default(self):
        self.fire(self.env(focus_safe_serials=[OWNER]))
        self.assertEqual(self.rows(), [])

    def test_warn_mode_records_one_content_free_line(self):
        self.fire(self.env(focus_safe="warn", focus_safe_serials=[OWNER]))
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hook"], fs.HOOK)
        self.assertEqual(rows[0]["tier"], "T1")
        self.assertFalse(rows[0]["blocked"])
        text = self.audit.read_text()
        self.assertNotIn(OWNER, text)
        self.assertNotIn("input", text)

    def test_an_ok_call_records_nothing(self):
        self.fire(self.env(focus_safe="warn", focus_safe_serials=[OWNER]),
                  args={"command": f"adb -s {OWNER} shell dumpsys window"})
        self.fire(self.env(focus_safe="warn", focus_safe_serials=[OWNER]), tool="read_file", args={"path": "x"})
        self.assertEqual(self.rows(), [])

    def test_warn_mode_without_devices_is_inert(self):
        self.fire(self.env(focus_safe="warn"))
        self.assertEqual(self.rows(), [])

    def test_an_agent_display_from_config_is_ok(self):
        self.fire(self.env(focus_safe="warn", focus_safe_serials=[OWNER], focus_safe_agent_displays=["7"]),
                  args={"command": f"adb -s {OWNER} shell input -d 7 tap 5 5"})
        self.assertEqual(self.rows(), [])

    def test_fails_open(self):
        env = self.env(focus_safe="warn", focus_safe_serials=[OWNER])
        with mock.patch.object(fs, "classify", side_effect=RuntimeError("boom")):
            self.fire(env)
        with mock.patch.object(fs, "config", side_effect=RuntimeError("boom")):
            self.fire(env)
        for args in (None, "adb shell input tap", 5):
            hook = fs.make_pre_tool_call(clock=lambda: NOW)
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertIsNone(hook(tool_name="terminal", args=args))
        self.assertIsNone(fs.make_pre_tool_call(clock=lambda: NOW)())

    def test_odd_config_is_off_or_inert(self):
        for cfg, want in (({"focus_safe": "block", "focus_safe_serials": [OWNER]}, 0),  # not a mode: off
                          ({"focus_safe": "warn", "focus_safe_serials": OWNER}, 1),     # one serial string
                          ({"focus_safe": "warn", "focus_safe_serials": [5, None]}, 0)):  # not this phone
            self.audit.unlink(missing_ok=True)
            self.fire(self.env(**cfg))
            self.assertEqual(len(self.rows()), want, cfg)

    def test_the_note_is_plain_and_digit_free(self):
        for r in fs.RULES:
            n = fs.note(r["why"])
            self.assertEqual(re.findall(r"\d", n), [], n)
            self.assertIn("agent display", n)


class Settings(unittest.TestCase):
    def test_settings_from_config(self):
        self.assertEqual(fs.settings({}), ("off", (), ()))
        self.assertEqual(fs.settings({"focus_safe": "warn", "focus_safe_serials": [OWNER, ""],
                                      "focus_safe_agent_displays": ["7", 9]}),
                         ("warn", (OWNER,), ("7", "9")))
        self.assertEqual(fs.settings({"focus_safe": "WARN", "focus_safe_serials": OWNER}), ("warn", (OWNER,), ()))
        self.assertEqual(fs.settings({"focus_safe": "block"})[0], "off")
        self.assertEqual(fs.settings("nope"), ("off", (), ()))


class Wired(unittest.TestCase):
    def test_the_plugin_registers_the_hook(self):
        from test_plugin import FakeCtx, load_plugin
        ctx = FakeCtx()
        load_plugin().register(ctx)
        self.assertEqual(len(ctx.hooks.get("pre_tool_call", [])), 1)


if __name__ == "__main__":
    unittest.main()
