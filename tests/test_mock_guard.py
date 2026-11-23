"""limitless/mock_guard.py: a demo, mock or sample wearable row is told apart from a real one by the markers the
source apps actually write (NOOP's demo seeders, Open Wearables' seed users) plus config ``mock_device_patterns``.

Synthetic ids only: no real device, model or serial.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import mock_guard as mg  # noqa: E402


class Markers(unittest.TestCase):
    def test_noop_demo_id_prefix(self):
        self.assertTrue(mg.is_mock("demo-band-a"))
        self.assertTrue(mg.is_mock("DEMO-band-a"))

    def test_noop_demo_id_suffix(self):
        self.assertTrue(mg.is_mock("band-a-demo"))

    def test_noop_demo_device_name(self):
        self.assertTrue(mg.is_mock("Band (demo)"))
        self.assertTrue(mg.is_mock({"id": "my-whoop", "name": "Band (demo)"}))

    def test_open_wearables_seed_user_name(self):
        self.assertTrue(mg.is_mock({"first_name": "[SEED:7|active] Synthetic"}))
        self.assertFalse(mg.is_mock({"first_name": "Synthetic"}))

    def test_real_ids_are_not_mock(self):
        for v in ("my-whoop", "whoop-0000aaaa", "oura-0000bbbb", "demographic-band", "band-demos", "", None, 3,
                  {"id": "whoop-0000aaaa", "name": "Band"}, {}, []):
            self.assertFalse(mg.is_mock(v), v)

    def test_a_row_dict_is_mock_when_any_device_field_is(self):
        self.assertTrue(mg.is_mock({"deviceId": "demo-band-a"}))
        self.assertTrue(mg.is_mock({"device_id": "band-a-demo"}))
        self.assertTrue(mg.is_mock({"device": "Band (demo)"}))
        self.assertTrue(mg.is_mock({"source": {"provider": "polar", "device_id": "demo-band-a"}}))
        self.assertFalse(mg.is_mock({"source": {"provider": "polar", "device": "Band"}}))

    def test_fields_that_are_not_device_fields_are_never_read(self):
        self.assertFalse(mg.is_mock({"night": "demo-x", "note": "Band (demo)", "source": "demo-x"}))


class ConfigPatterns(unittest.TestCase):
    CFG = {"mock_device_patterns": ["sim-*", " *-sample ", 3, "", None]}

    def test_default_is_empty(self):
        for cfg in (None, {}, {"mock_device_patterns": None}, {"mock_device_patterns": "sim-*"},
                    {"mock_device_patterns": [1, " "]}):
            self.assertEqual(mg.patterns(cfg), (), cfg)

    def test_configured_glob_patterns_case_insensitive(self):
        self.assertEqual(mg.patterns(self.CFG), ("sim-*", "*-sample"))
        self.assertTrue(mg.is_mock("SIM-band-a", self.CFG))
        self.assertTrue(mg.is_mock({"deviceId": "band-a-sample"}, self.CFG))
        self.assertFalse(mg.is_mock("sim-band-a"))            # without the config it is a real id
        self.assertFalse(mg.is_mock("band-a", self.CFG))


class Split(unittest.TestCase):
    def test_mixed(self):
        rows = [{"deviceId": "whoop-0000aaaa"}, {"deviceId": "demo-band-a"}, {"deviceId": "sim-1"},
                {"deviceId": "oura-0000bbbb"}]
        real, n = mg.split(rows, {"mock_device_patterns": ["sim-*"]})
        self.assertEqual(real, [rows[0], rows[3]])
        self.assertEqual(n, 2)

    def test_all_real_is_unchanged(self):
        rows = [{"deviceId": "whoop-0000aaaa"}, {"deviceId": "my-whoop"}]
        self.assertEqual(mg.split(rows), (rows, 0))

    def test_only_mock(self):
        self.assertEqual(mg.split(["demo-a", "b-demo"]), ([], 2))

    def test_left_out_words_have_no_digit(self):
        self.assertEqual(mg.LEFT_OUT, "some demo rows were left out")
        for s in (mg.LEFT_OUT, mg.ONLY_DEMO):
            self.assertFalse(any(c.isdigit() for c in s), s)
        self.assertTrue(mg.ONLY_DEMO.startswith("no wearable data"))


if __name__ == "__main__":
    unittest.main()
