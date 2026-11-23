"""limitless_status, the doctor's input rows and the breathing line's heart words never call an input live from a
demo or sample device (limitless/mock_guard.py): an inputs.json name with a demo mark, or matching config
``mock_device_patterns``, is state "demo" (no age, listed as unknown), never "recording". Real inputs read as
before. Synthetic only.
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import doctor, tools, wind_down  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 1894708800.0
CFG = {"mock_device_patterns": ["sim-*"]}


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name)

    def inputs(self, ages):
        (self.st / "inputs.json").write_text(json.dumps({"at": iso(NOW - 1800), "ageHours": ages}))
        return StateReader(self.st)


class Status(Base):
    def test_a_demo_input_is_never_recording(self):
        st = tools.status(self.inputs({"demo-band-a": 0.1, "band-b-demo": 0.2, "wearable": 1.0}), NOW)["value"]
        self.assertEqual(st["inputs"]["demo-band-a"], {"age_h": None, "state": "demo"})
        self.assertEqual(st["inputs"]["band-b-demo"], {"age_h": None, "state": "demo"})
        self.assertEqual(st["inputs"]["wearable"], {"age_h": 1.5, "state": "recording"})
        self.assertEqual(st["unknown"], ["band-b-demo", "demo-band-a"])
        self.assertEqual(st["not_recording"], [])

    def test_a_config_pattern_makes_an_input_demo(self):
        r = self.inputs({"sim-band-c": 0.1})
        self.assertEqual(tools.status(r, NOW, cfg=CFG)["value"]["inputs"]["sim-band-c"]["state"], "demo")
        self.assertEqual(tools.status(r, NOW)["value"]["inputs"]["sim-band-c"]["state"], "recording")

    def test_only_demo_inputs_none_is_live(self):
        st = tools.status(self.inputs({"demo-band-a": 0.1}), NOW)["value"]
        self.assertNotIn("recording", [v["state"] for v in st["inputs"].values()])

    def test_all_real_inputs_are_unchanged(self):
        st = tools.status(self.inputs({"wearable": 1.0, "phone": 30.0, "bike": "down"}), NOW)["value"]
        self.assertEqual(st["inputs"], {"bike": {"age_h": None, "state": "down"},
                                        "phone": {"age_h": 30.5, "state": "not recording"},
                                        "wearable": {"age_h": 1.5, "state": "recording"}})
        self.assertEqual((st["not_recording"], st["unknown"]), (["bike", "phone"], []))


class Doctor(Base):
    def test_a_demo_input_row_is_missing_never_live_in_words(self):
        rows = doctor.input_rows(tools.status(self.inputs({"demo-band-a": 0.1, "wearable": 1.0}), NOW))
        by = {r["name"]: r for r in rows}
        self.assertEqual(by["input demo-band-a"]["status"], "missing")
        self.assertIn("demo", by["input demo-band-a"]["reason"])
        self.assertEqual(by["input wearable"]["status"], "live")
        for r in rows:
            self.assertNotRegex(r["reason"], r"\d")

    def test_the_doctor_applies_the_config_pattern(self):
        self.inputs({"sim-band-c": 0.1})
        rows = doctor.report(dict(CFG, state=str(self.st)), NOW)
        r = [r for r in rows if r["name"] == "input sim-band-c"][0]
        self.assertEqual(r["status"], "missing")


class HeartWords(Base):
    def test_a_demo_wearable_input_never_gives_live_heart_data(self):
        inp = {"at": iso(NOW - 1800), "ageHours": {"demo-band-a": 0.1}}
        self.assertEqual(wind_down.wearable_inputs({"wearable_inputs": ["demo-band-a"]}), ())
        self.assertFalse(wind_down.wearable_live(inp, NOW, wind_down.wearable_inputs(
            {"wearable_inputs": ["demo-band-a"]})))
        self.assertFalse(wind_down.wearable_live(inp, NOW, ("demo-band-a",)))

    def test_a_config_pattern_drops_a_configured_wearable_input(self):
        cfg = dict(CFG, wearable_inputs=["sim-band-c", "band-d"])
        self.assertEqual(wind_down.wearable_inputs(cfg), ("band-d",))

    def test_real_names_are_unchanged(self):
        self.assertEqual(wind_down.wearable_inputs({}), ("wearable",))
        self.assertEqual(wind_down.wearable_inputs({"wearable_inputs": ["band_a", " band_b "]}), ("band_a", "band_b"))
        inp = {"at": iso(NOW - 1800), "ageHours": {"band_a": 0.1}}
        self.assertTrue(wind_down.wearable_live(inp, NOW, ("band_a",)))


if __name__ == "__main__":
    unittest.main()
