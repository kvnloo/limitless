"""limitless_breathing: read-only, whether a breathing link is set and whether live heart data backs it, in words.

The link itself only under LIMITLESS_RAW_IN_PROMPT=1; otherwise "a link is set". Modality derived, age_h the
wearable input's age (limitless_status's rule), a digit-free T1 label. Synthetic link and inputs only."""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from limitless import plugin, wind_down  # noqa: E402
from test_plugin import FakeCtx, manifest_list  # noqa: E402

NOW = 1894708800.0
FIELDS = {"value", "modality", "age_h", "evidence_tier"}
LINK = "example://breathe"
NAME = "limitless_breathing"


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Tool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.audit = self.dir / "audit.jsonl"

    def call(self, raw=False, wearable=None, **cfg):
        path = self.dir / "config.json"
        cfg["audit_path"] = str(self.audit)
        path.write_text(json.dumps(cfg))
        if wearable is not None:
            (self.dir / "inputs.json").write_text(json.dumps({"at": iso(NOW - 1800), "ageHours":
                                                              {"wearable": wearable}}))
        env = {"LIMITLESS_CONFIG": str(path), "LIMITLESS_STATE": str(self.dir)}
        if raw:
            env["LIMITLESS_RAW_IN_PROMPT"] = "1"
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(time, "time", return_value=NOW):
            return json.loads(plugin._handler(plugin.TOOLS[NAME][1], NAME)({}))

    def shape(self, res):
        self.assertTrue(FIELDS <= set(res), res)
        self.assertEqual(res["modality"], "derived")
        self.assertEqual(res["label"]["tier"], "T1")
        self.assertEqual(re.findall(r"\d", res["label"]["label"]), [], res)
        return res

    def test_off_by_default(self):
        res = self.shape(self.call())
        self.assertEqual(res["value"], {"link_set": False, "heart_data": "without heart data"})
        self.assertEqual(res["label"]["label"], "breathing link off")
        self.assertIsNone(res["age_h"])

    def test_set_hides_the_link_without_the_opt_in(self):
        res = self.shape(self.call(**{wind_down.BREATHING_KEY: LINK}))
        self.assertEqual(res["value"], {"link_set": True, "heart_data": "without heart data", "link": "a link is set"})
        self.assertNotIn("breathe", json.dumps(res))
        self.assertEqual(res["label"]["label"], "breathing link set, without heart data")

    def test_raw_opt_in_shows_the_link(self):
        res = self.shape(self.call(raw=True, **{wind_down.BREATHING_KEY: LINK}))
        self.assertEqual(res["value"]["link"], LINK)

    def test_live_wearable(self):
        res = self.shape(self.call(wearable=1.0, **{wind_down.BREATHING_KEY: LINK}))
        self.assertEqual(res["value"]["heart_data"], "with live heart data")
        self.assertEqual(res["label"]["label"], "breathing link set, with live heart data")
        self.assertEqual((res["age_h"], res["evidence_tier"]), (1.5, "direct"))

    def test_stale_or_down_wearable(self):
        res = self.shape(self.call(wearable=40.0, **{wind_down.BREATHING_KEY: LINK}))
        self.assertEqual((res["value"]["heart_data"], res["age_h"], res["evidence_tier"]),
                         ("without heart data", 40.5, "stale"))
        res = self.shape(self.call(wearable="down", **{wind_down.BREATHING_KEY: LINK}))
        self.assertEqual((res["value"]["heart_data"], res["age_h"]), ("without heart data", None))

    def test_a_link_that_cannot_ride_says_so_without_echoing_it(self):
        res = self.shape(self.call(raw=True, **{wind_down.BREATHING_KEY: "example://breathe4"}))
        self.assertFalse(res["value"]["link_set"])
        self.assertNotIn("link", res["value"])
        self.assertIn("not used", res["value"]["note"])
        self.assertNotIn("breathe4", json.dumps(res))
        self.assertEqual(re.findall(r"\d", res["value"]["note"]), [])

    def test_read_only_and_audited(self):
        before = sorted(p.name for p in self.dir.iterdir())
        self.call(**{wind_down.BREATHING_KEY: LINK})
        after = sorted(p.name for p in self.dir.iterdir())
        self.assertEqual(set(after) - set(before), {"config.json", "audit.jsonl"})   # the test's config, the
                                                                                     # opt-in audit line: nothing else
        rows = [json.loads(x) for x in self.audit.read_text().splitlines()]
        self.assertEqual([r["hook"] for r in rows], [f"tool:{NAME}"])
        self.assertEqual((rows[0]["tier"], rows[0]["blocked"]), ("T1", False))

    def test_registered_and_in_the_manifest(self):
        ctx = FakeCtx()
        plugin.register(ctx)
        self.assertIn(NAME, sorted(ctx.tools))
        self.assertIn(NAME, manifest_list("provides_tools"))
        desc = plugin.TOOLS[NAME][0]["description"].lower()
        for w in ("read-only", "raw opt-in", "suggest"):
            self.assertIn(w, desc)


if __name__ == "__main__":
    unittest.main()
