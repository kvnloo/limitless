"""Which inputs.json names count as the wearable for the breathing choice's heart words: config
``wearable_inputs`` (a list of input names, default ["wearable"]); the freshest named input wins. A host whose
sync names its inputs after each device would otherwise never be "with live heart data". Synthetic only."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from limitless import tools, wind_down  # noqa: E402
from limitless.envelope import STALE_H  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
import test_wind_down_breathing_heart as heart  # noqa: E402

NOW, H, LINK, LIVE, NONE = heart.NOW, heart.H, heart.LINK, heart.LIVE, heart.NONE


def inputs(ages, snap_age_h=0.5):
    return {"at": heart.iso(NOW - snap_age_h * H), "ageHours": dict(ages)}


class Names(unittest.TestCase):
    def test_default_is_wearable(self):
        for cfg in (None, {}, {"wearable_inputs": None}, {"wearable_inputs": "band_a"},
                    {"wearable_inputs": []}, {"wearable_inputs": [1, "", "  "]}):
            self.assertEqual(wind_down.wearable_inputs(cfg), ("wearable",), cfg)

    def test_configured_names(self):
        self.assertEqual(wind_down.wearable_inputs({"wearable_inputs": ["band_a", " band_b ", 3]}),
                         ("band_a", "band_b"))


class FreshestWins(unittest.TestCase):
    def test_freshest_named_input(self):
        inp = inputs({"band_a": 300.0, "band_b": 1.0, "phone": 0.1})
        self.assertEqual(wind_down.wearable_age_h(inp, NOW, ("band_a", "band_b")), 1.5)
        self.assertTrue(wind_down.wearable_live(inp, NOW, ("band_a", "band_b")))

    def test_down_or_stale_names_are_not_live(self):
        inp = inputs({"band_a": "down", "band_b": STALE_H + 2})
        self.assertFalse(wind_down.wearable_live(inp, NOW, ("band_a", "band_b")))
        self.assertIsNone(wind_down.wearable_age_h(inputs({"band_a": "down"}), NOW, ("band_a",)))

    def test_unnamed_inputs_never_count(self):
        self.assertFalse(wind_down.wearable_live(inputs({"phone": 0.1}), NOW, ("band_a",)))
        self.assertFalse(wind_down.wearable_live(inputs({"band_a": 0.1}), NOW))     # default name only


class Miq(heart.Miq):
    def write(self, inp):
        self.cfg.write_text(json.dumps({wind_down.BREATHING_KEY: LINK, "wearable_inputs": ["band_a", "band_b"]}))
        if inp is not None:
            (self.st / "inputs.json").write_text(json.dumps(inp))

    def test_live_named_input(self):
        self.write(inputs({"band_a": 400.0, "band_b": 0.4}))
        self.assertEqual(self.line(), LIVE)

    def test_stale_named_inputs(self):
        self.write(inputs({"band_a": 400.0, "band_b": STALE_H + 3}))
        self.assertEqual(self.line(), NONE)

    # the inherited cases use the "wearable" name, which this config no longer counts
    test_live_wearable = None
    test_without_state_dir_is_not_live = None


class Tool(unittest.TestCase):
    def test_breathing_tool_reads_the_configured_names(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "inputs.json").write_text(json.dumps(inputs({"band_b": 0.4})))
            (d / "config.json").write_text(json.dumps({wind_down.BREATHING_KEY: LINK,
                                                       "wearable_inputs": ["band_b"]}))
            got = tools.breathing(StateReader(d), NOW, env={"LIMITLESS_CONFIG": str(d / "config.json")}, home=d)
            self.assertEqual(got["value"]["heart_data"], wind_down.HEART_LIVE)
            self.assertEqual(got["age_h"], 0.9)


if __name__ == "__main__":
    unittest.main()
