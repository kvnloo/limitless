"""limitless_focus_safe: the guard's mode, protected devices and this week's warnings in words. Read-only.
Synthetic serials and audit rows only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import focus_safe as fs  # noqa: E402
from limitless import plugin  # noqa: E402

NOW = 1894708800.0
FIELDS = {"value", "modality", "age_h", "evidence_tier"}


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Tool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.audit = self.dir / "audit.jsonl"

    def call(self, audit=True, **cfg):
        path = self.dir / "config.json"
        if audit:
            cfg["audit_path"] = str(self.audit)
        path.write_text(json.dumps(cfg))
        env = {"LIMITLESS_CONFIG": str(path), "LIMITLESS_STATE": str(self.dir)}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(time, "time", return_value=NOW):
            return json.loads(plugin._handler(plugin.TOOLS["limitless_focus_safe"][1], "limitless_focus_safe")({}))

    def rows(self, *ages_h, hook=fs.HOOK):
        with self.audit.open("a") as f:
            for a in ages_h:
                f.write(json.dumps({"at": iso(NOW - a * 3600), "hook": hook, "tier": "T1", "lines": 1, "digits": 0,
                                    "opt_in": False, "sha256": "0" * 64, "blocked": False}) + "\n")

    def test_off_by_default(self):
        res = self.call()
        self.assertTrue(FIELDS <= set(res))
        self.assertEqual(res["value"]["mode"], "off")
        self.assertEqual(res["value"]["protected_devices"], "no devices")
        self.assertEqual(res["label"]["label"], "focus guard off")
        self.assertEqual(res["label"]["tier"], "T1")

    def test_warn_mode_with_two_devices(self):
        self.rows(1, 30, 24 * 6, 24 * 8)  # three inside the week, one older
        self.rows(2, hook="tool:limitless_status")  # another hook's row is not a warning
        res = self.call(focus_safe="warn", focus_safe_serials=["SYNTHETIC0001", "SYNTHETIC0002"])
        self.assertEqual(res["value"], {"mode": "warn", "protected_devices": "two devices",
                                        "last_warnings_this_week": "three this week"})
        self.assertEqual(res["label"]["label"], "focus guard warns: two devices protected")

    def test_one_device_no_warnings(self):
        self.rows(24 * 9)
        res = self.call(focus_safe="warn", focus_safe_serials=["SYNTHETIC0001"])
        self.assertEqual(res["value"]["protected_devices"], "one device")
        self.assertEqual(res["value"]["last_warnings_this_week"], "none this week")

    def test_warn_mode_with_nothing_protected_is_inert(self):
        res = self.call(focus_safe="warn")
        self.assertEqual(res["label"]["label"], "focus guard warns: nothing protected")

    def test_audit_off_is_unknown_never_none(self):
        res = self.call(audit=False, focus_safe="warn", focus_safe_serials=["SYNTHETIC0001"])
        self.assertEqual(res["value"]["last_warnings_this_week"], "unknown: the audit log is off")

    def test_many(self):
        self.rows(*range(1, 15))
        res = self.call(focus_safe="warn", focus_safe_serials=[f"SYNTHETIC{n:04d}" for n in range(1, 13)])
        self.assertEqual(res["value"]["protected_devices"], "many devices")
        self.assertEqual(res["value"]["last_warnings_this_week"], "many this week")

    def test_digit_free_and_no_serial_anywhere(self):
        self.rows(1)
        res = self.call(focus_safe="warn", focus_safe_serials=["SYNTHETIC0001"], focus_safe_agent_displays=["7"])
        text = json.dumps(res)
        self.assertNotIn("SYNTHETIC", text)
        self.assertEqual(re.findall(r"\d", " ".join([*res["value"].values(), res["label"]["label"]])), [])

    def test_read_only(self):
        self.rows(1)
        before = self.audit.read_text()
        self.call(focus_safe="warn", focus_safe_serials=["SYNTHETIC0001"])
        after = self.audit.read_text().splitlines()
        self.assertTrue(after[0] == before.strip())  # only the tool's own label audit line may follow
        self.assertTrue(all(json.loads(x)["hook"] == "tool:limitless_focus_safe" for x in after[1:]))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["audit.jsonl", "config.json"])

    def test_registered_in_the_manifest(self):
        self.assertIn("limitless_focus_safe", plugin.TOOLS)
        self.assertIn("  - limitless_focus_safe", (Path(__file__).resolve().parents[1] / "plugin.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
