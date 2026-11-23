"""limitless_result_tier: whether the result tier filter is on, how many tool globs are set and the raw-numbers
opt-in, in words, with a digit-free T1 label; and its limitless-doctor row. Read-only. Synthetic globs only."""
import json
import os
import re
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import doctor, plugin  # noqa: E402
from limitless import result_tier as rt  # noqa: E402

NOW = 1894708800.0
FIELDS = {"value", "modality", "age_h", "evidence_tier"}


def host():
    mod = types.ModuleType("hermes_cli.plugins")
    mod.VALID_HOOKS = {rt.HOOK_NAME}
    return mock.patch.dict(sys.modules, {"hermes_cli.plugins": mod})


class Tool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def env(self, **cfg):
        path = self.dir / "config.json"
        path.write_text(json.dumps(cfg))
        return {"LIMITLESS_CONFIG": str(path), "LIMITLESS_STATE": str(self.dir)}

    def call(self, **cfg):
        with mock.patch.dict(os.environ, self.env(**cfg), clear=True), \
                mock.patch.object(time, "time", return_value=NOW):
            return json.loads(plugin._handler(plugin.TOOLS["limitless_result_tier"][1], "limitless_result_tier")({}))

    def test_off_by_default(self):
        res = self.call()
        self.assertTrue(FIELDS <= set(res))
        self.assertEqual(res["value"], {"filter": "off", "tool_globs": "no globs", "raw_numbers_opt_in": "off",
                                        "host_hook": rt.HOOK_UNKNOWN})
        self.assertEqual(res["label"], {"label": "result filter off: no health tools listed", "tier": "T1",
                                        "modality": "derived"})
        self.assertEqual((res["modality"], res["age_h"]), ("derived", None))

    def test_on_with_two_globs_on_a_host_that_knows_the_hook(self):
        with host():
            res = self.call(t0_tools=["mcp__synthetic_health__*", "fake_vitals"])
        self.assertEqual(res["value"], {"filter": "on", "tool_globs": "two globs", "raw_numbers_opt_in": "off",
                                        "host_hook": "known"})
        self.assertEqual(res["label"]["label"], "result filter on: two tool globs")

    def test_on_but_the_host_has_no_hook(self):
        res = self.call(t0_tools="fake_*")
        self.assertEqual(res["value"]["tool_globs"], "one glob")
        self.assertEqual(res["label"]["label"], "result filter on: one tool glob, but this host has no result hook")

    def test_the_opt_in_turns_it_off(self):
        res = self.call(t0_tools=["fake_*"], raw_numbers_opt_in=True)
        self.assertEqual((res["value"]["filter"], res["value"]["raw_numbers_opt_in"]), ("off", "on"))
        self.assertEqual(res["label"]["label"], "result filter off: raw numbers opted in")

    def test_many_globs_and_no_digit_anywhere(self):
        res = self.call(t0_tools=[f"fake_{i}_*" for i in range(14)])
        self.assertEqual(res["value"]["tool_globs"], "many globs")
        self.assertFalse(re.search(r"\d", json.dumps(res["value"]) + res["label"]["label"]))

    def test_a_glob_is_never_named(self):
        res = self.call(t0_tools=["mcp__synthetic_health__*"])
        self.assertNotIn("synthetic_health", json.dumps(res))

    def test_registered_with_a_schema_and_in_the_manifest(self):
        schema = plugin.TOOLS["limitless_result_tier"][0]
        self.assertEqual(schema["name"], "limitless_result_tier")
        self.assertIn("Read-only", schema["description"])
        self.assertIn("limitless_result_tier", (Path(__file__).parents[1] / "plugin.yaml").read_text())


class Doctor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def row(self, **cfg):
        path = self.dir / "config.json"
        path.write_text(json.dumps(cfg))
        env = {"LIMITLESS_CONFIG": str(path), "LIMITLESS_STATE": str(self.dir)}
        with mock.patch.dict(os.environ, env, clear=True):
            return doctor.tool_row("limitless_result_tier", NOW)

    def test_no_globs_is_off_with_the_config_key(self):
        r = self.row()
        self.assertEqual((r["status"], r["reason"]), ("off", "no health tools listed (config t0_tools)"))

    def test_the_printed_row_keeps_the_config_key(self):
        self.assertEqual(doctor.words("no health tools listed (config t0_tools)"),
                         "no health tools listed (config t0_tools)")
        self.assertEqual(doctor.words("over 3 hours, 1.5 days"), "over a number hours, a number days")
        self.assertEqual(doctor.words("set v2 and t0_tools_x9"), "set va number and t0_tools_xa number")

    def test_globs_set_is_not_off(self):
        self.assertNotEqual(self.row(t0_tools=["fake_*"])["status"], "off")


if __name__ == "__main__":
    unittest.main()
