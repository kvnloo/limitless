"""limitless_outages: the current input outages in words, read-only. Synthetic state; nothing real."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from limitless import doctor, outage, plugin  # noqa: E402
from test_plugin import FakeCtx, manifest_list  # noqa: E402

NAME = "limitless_outages"
NOW = 1894708800.0
H = 3600.0


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Tool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg_path = self.root / "config.json"
        self.config({})

    def config(self, cfg):
        self.cfg_path.write_text(json.dumps(dict(cfg, state=str(self.st))))

    def inputs(self, at, ages):
        (self.st / "inputs.json").write_text(json.dumps({"at": iso(at), "ageHours": ages}))

    def call(self, now=NOW):
        env = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
        env.update(HOME=str(self.root), LIMITLESS_CONFIG=str(self.cfg_path), LIMITLESS_STATE=str(self.st))
        with mock.patch.dict(os.environ, env, clear=True):
            return plugin.TOOLS[NAME][1]({}, now)

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.st.iterdir()}

    def test_current_outages_in_words(self):
        self.inputs(NOW, {"wearable": 50.0, "phone_screen": "down", "laptop": 1.0})
        res = self.call()
        self.assertEqual(res["value"], {"label": "not recording: wearable (since about two days ago) and phone "
                                                 "screen (since just now)", "inputs": ["phone screen", "wearable"]})
        self.assertEqual((res["modality"], res["age_h"]), ("derived", None))
        self.assertEqual(res["label"], {"label": res["value"]["label"], "tier": "T1", "modality": "derived"})
        self.assertIsNone(re.search(r"\d", json.dumps(res["value"])))

    def test_every_input_recording(self):
        self.inputs(NOW, {"wearable": 1.0})
        self.assertEqual(self.call()["value"], {"label": "every input is recording", "inputs": []})

    def test_told_outages_still_show(self):
        self.inputs(NOW, {"wearable": 50.0})
        outage.poll(self.st, NOW, {})
        outage.tell(self.st, ["wearable"], NOW)
        self.assertEqual(self.call(NOW + H)["value"]["inputs"], ["wearable"])

    def test_ignored_inputs_and_off(self):
        self.inputs(NOW, {"wearable": 50.0, "scale": 500.0})
        self.config({"outage_ignore": ["scale"]})
        self.assertEqual(self.call()["value"]["inputs"], ["wearable"])
        self.config({"input_outage": False})
        self.assertEqual(self.call()["value"], {"label": "off", "why": outage.OFF_WHY})

    def test_no_inputs_file_is_no_value_with_a_reason(self):
        res = self.call()
        self.assertIsNone(res["value"])
        self.assertTrue(res["reason"])

    def test_nothing_is_written(self):
        self.inputs(NOW, {"wearable": 50.0, "phone": "down"})
        outage.poll(self.st, NOW, {})
        before = self.snapshot()
        self.call(NOW + 5 * H)
        self.assertEqual(self.snapshot(), before)
        (self.st / outage.MARK_FILE).unlink()
        before = self.snapshot()
        self.call()
        self.assertEqual(self.snapshot(), before)


class Registered(unittest.TestCase):
    def test_in_the_manifest_and_registered(self):
        self.assertIn(NAME, manifest_list("provides_tools"))
        self.assertIn(NAME, plugin.TOOLS)
        ctx = FakeCtx()
        plugin.register(ctx)
        self.assertIn(NAME, ctx.tools)

    def test_doctor_says_off_when_off(self):
        env = {"value": {"label": "off", "why": outage.OFF_WHY}, "modality": "derived", "age_h": None,
               "evidence_tier": "direct"}
        self.assertEqual(doctor.classify(NAME, env), (doctor.OFF, outage.OFF_WHY + " (config input_outage)"))


if __name__ == "__main__":
    unittest.main()
