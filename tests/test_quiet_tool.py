"""limitless_quiet: the quiet state as a read-only envelope with a digit-free T1 label. Synthetic data only."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import plugin, quiet, tools  # noqa: E402

NOW = 2_000_000_000.0


class QuietTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.st / "none.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def tool(self):
        return tools.quiet(self.st, NOW, env=self.env, home=self.st)

    def test_no_file_is_on(self):
        out = self.tool()
        self.assertEqual(out["value"], {"mode": "on", "set": "on", "held": False, "why": quiet.WHY_ON})
        self.assertEqual(out["modality"], "self_report")
        self.assertEqual(out["label"], {"label": "on", "tier": "T1", "modality": "self_report"})

    def test_off(self):
        quiet.write(self.st, "off", NOW - 1800)
        out = self.tool()
        self.assertEqual(out["value"]["mode"], "off")
        self.assertTrue(out["value"]["held"])
        self.assertEqual(out["value"]["why"], "quiet: off until you reply on")
        self.assertEqual(out["label"]["label"], "off")
        self.assertEqual(out["age_h"], 0.5)

    def test_quiet_tonight_and_its_end(self):
        quiet.write(self.st, "quiet_tonight", NOW - 1800)
        self.assertEqual(self.tool()["label"]["label"], "quiet tonight")
        (self.st / "events.jsonl").write_text(json.dumps({"event": "wake", "at": NOW - 60}) + "\n")
        out = self.tool()
        self.assertEqual((out["value"]["mode"], out["value"]["set"]), ("on", "quiet_tonight"))
        self.assertFalse(out["value"]["held"])
        self.assertEqual(out["label"]["label"], "on")

    def test_snoozed(self):
        quiet.write(self.st, "snoozed", NOW - 1800)
        beacon = self.st / "beacon.json"
        beacon.write_text(json.dumps({"at": quiet.iso(NOW - 1800), "v": 1}))
        self.env["LIMITLESS_OWNER_BEACONS"] = str(beacon)
        out = self.tool()
        self.assertEqual(out["label"]["label"], "snoozed")
        self.assertEqual(out["value"]["why"], "quiet: snoozed until you write again")

    def test_labels_and_whys_are_digit_free(self):
        for mode in quiet.MODES:
            quiet.write(self.st, mode, NOW - 1800)
            out = self.tool()
            for s in (out["label"]["label"], out["value"]["why"], out["value"]["mode"]):
                self.assertFalse(any(c.isdigit() for c in s), s)

    def test_read_only(self):
        quiet.write(self.st, "off", NOW - 1800)
        before = sorted((p.name, p.stat().st_mtime_ns) for p in self.st.iterdir())
        self.tool()
        self.assertEqual(sorted((p.name, p.stat().st_mtime_ns) for p in self.st.iterdir()), before)

    def test_through_the_plugin_handler(self):
        quiet.write(self.st, "off", NOW - 1800)
        self.assertIn("limitless_quiet", plugin.TOOLS)
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(time, "time", return_value=NOW):
            res = json.loads(plugin._handler(plugin.TOOLS["limitless_quiet"][1], "limitless_quiet")({}))
        self.assertEqual(res["value"]["mode"], "off")
        self.assertEqual(res["label"], {"label": "off", "tier": "T1", "modality": "self_report"})

    def test_schema_takes_no_arguments_and_says_it_only_reads(self):
        schema = plugin.TOOLS["limitless_quiet"][0]
        self.assertEqual(schema["parameters"]["properties"], {})
        self.assertIn("Read-only", schema["description"])


if __name__ == "__main__":
    unittest.main()
