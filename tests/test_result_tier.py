"""result_tier: a health tool's raw readings never enter the prompt. For a tool whose name matches a config
t0_tools glob, every number in its result becomes the words "a number"; keys and words stay, JSON stays JSON.
Made-up tool names and readings only."""
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import result_tier as rt  # noqa: E402

CFG = {"t0_tools": ["mcp__synthetic_health__*", "fake_vitals"]}
TOOL = "mcp__synthetic_health__get_night"


class Text(unittest.TestCase):
    def test_every_number_in_plain_text_becomes_words(self):
        out = rt.transform(TOOL, "resting heart rate 61 bpm, hrv 47.5ms, temp -0.3, score: 88%", cfg=CFG)
        self.assertIsInstance(out, str)
        self.assertFalse(re.search(r"\d", out), out)
        self.assertEqual(out, "resting heart rate a number bpm, hrv a number ms, temp a number, score: a number%")

    def test_timestamps_times_and_ids_are_replaced_whole(self):
        out = rt.transform(TOOL, "night 2031-02-03T23:41:07Z to 06:58, id 4521, ref 3f9a2b7c, "
                                 "uuid 0f8fad5b-d9cb-469f-a165-70867728950e", cfg=CFG)
        self.assertEqual(out, "night a number to a number, id a number, ref a number, uuid a number")

    def test_ranges_and_pairs_keep_their_separator(self):
        self.assertEqual(rt.transform(TOOL, "pressure 118/76, band 50-60", cfg=CFG),
                         "pressure a number/a number, band a number-a number")

    def test_field_names_with_a_digit_stay(self):
        self.assertEqual(rt.transform(TOOL, "spo2: 97, hr_7d: 60", cfg=CFG), "spo2: a number, hr_7d: a number")

    def test_text_with_no_number_is_left_alone(self):
        self.assertIsNone(rt.transform(TOOL, "no reading yet", cfg=CFG))


class Json(unittest.TestCase):
    RESULT = {"night": {"start": "2031-02-03T23:41:07Z", "hr": 61, "hrv_ms": 47.5, "stages": [12, 88, 31],
                        "note": "woke 2 times", "ok": True, "source": None}, "id": 4521, "spo2": "97%"}

    def test_json_stays_valid_with_the_same_keys(self):
        out = rt.transform(TOOL, json.dumps(self.RESULT), cfg=CFG)
        got = json.loads(out)
        self.assertEqual(list(got), list(self.RESULT))
        self.assertEqual(list(got["night"]), list(self.RESULT["night"]))
        self.assertEqual(got["night"]["hr"], "a number")
        self.assertEqual(got["night"]["stages"], ["a number"] * 3)
        self.assertEqual(got["night"]["start"], "a number")
        self.assertEqual(got["night"]["note"], "woke a number times")
        self.assertIs(got["night"]["ok"], True)
        self.assertIsNone(got["night"]["source"])
        self.assertEqual(got["id"], "a number")
        self.assertEqual(got["spo2"], "a number%")
        self.assertFalse(re.search(r"\d", out.replace("spo2", "").replace("hrv_ms", "")), out)

    def test_a_bare_json_number(self):
        self.assertEqual(json.loads(rt.transform("fake_vitals", "72", cfg=CFG)), "a number")

    def test_replace_counts_every_number(self):
        _, n = rt.scrub(json.dumps(self.RESULT))
        self.assertEqual(n, 9)
        self.assertEqual(rt.scrub("hr 61 at 06:58")[1], 2)


class Gates(unittest.TestCase):
    def test_a_tool_no_glob_matches_is_untouched(self):
        self.assertIsNone(rt.transform("mcp__other_server__get_night", "hr 61", cfg=CFG))
        self.assertIsNone(rt.transform("terminal", "hr 61", cfg=CFG))

    def test_no_globs_by_default_the_filter_does_nothing(self):
        self.assertIsNone(rt.transform(TOOL, "hr 61", cfg={}))
        self.assertIsNone(rt.transform(TOOL, "hr 61", cfg={"t0_tools": []}))

    def test_the_raw_numbers_opt_in_leaves_results_alone(self):
        self.assertIsNone(rt.transform(TOOL, "hr 61", cfg=dict(CFG, raw_numbers_opt_in=True)))
        self.assertIsInstance(rt.transform(TOOL, "hr 61", cfg=dict(CFG, raw_numbers_opt_in="yes")), str)

    def test_an_error_result_is_left_alone(self):
        self.assertIsNone(rt.transform(TOOL, "timeout after 30 s", status="error", cfg=CFG))
        self.assertIsNone(rt.transform(TOOL, json.dumps({"error": "rate limit 429"}), cfg=CFG))

    def test_malformed_results_and_config_never_raise(self):
        for bad in (b"hr 61", {"hr": 61}, None, 61, ["hr", 61]):
            self.assertIsNone(rt.transform(TOOL, bad, cfg=CFG), bad)
        for cfg in (None, [], {"t0_tools": 7}, {"t0_tools": [None, 3, ""]}, "t0_tools"):
            self.assertIsNone(rt.transform(TOOL, "hr 61", cfg=cfg), cfg)
        self.assertIsNone(rt.transform(None, "hr 61", cfg=CFG))

    def test_one_glob_string_is_a_list_of_one(self):
        self.assertEqual(rt.settings({"t0_tools": "fake_*"}), (("fake_*",), False))

    def test_the_matching_glob(self):
        self.assertEqual(rt.matching_glob("fake_vitals", CFG["t0_tools"]), "fake_vitals")
        self.assertEqual(rt.matching_glob(TOOL, CFG["t0_tools"]), "mcp__synthetic_health__*")
        self.assertIsNone(rt.matching_glob("FAKE_VITALS", CFG["t0_tools"]))  # case-sensitive, as tool names are


if __name__ == "__main__":
    unittest.main()
