"""Every tool result keeps the evidence envelope; a T1 label sits next to the value only where the envelope
allows it (a value to label, no label yet). Synthetic fixtures only."""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import envelope as e  # noqa: E402
from limitless import plugin, tools  # noqa: E402
from test_plugin import owner_db  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state"
CARD = ROOT / "tests" / "fixtures" / "scorecard" / "scorecard.md"
NOW = 1894708800.0
FIELDS = {"value", "modality", "age_h", "evidence_tier"}
T1 = {"label": "fresh", "tier": "T1", "modality": "measured"}


class WithLabel(unittest.TestCase):
    def test_adds_the_label_next_to_the_value(self):
        env = e.envelope({"x": 1}, "measured", 2.0)
        out = e.with_label(env, T1)
        self.assertEqual(out["label"], T1)
        self.assertEqual({k: out[k] for k in FIELDS}, env)
        self.assertNotIn("label", env)  # the input is not changed

    def test_a_null_value_gets_no_label(self):
        for env in (e.missing("no data"), e.envelope(None, "proxy", 1.0, reason="no data")):
            self.assertEqual(e.with_label(env, T1), env)

    def test_an_existing_label_is_kept(self):
        env = dict(e.envelope("short", "proxy", 1.0), label={"label": "short", "tier": "T1", "modality": "proxy"})
        self.assertEqual(e.with_label(env, T1)["label"]["label"], "short")

    def test_only_a_digit_free_t1_label_is_added(self):
        env = e.envelope(5, "measured", 1.0)
        for bad in ({"label": "5 h", "tier": "T1", "modality": None}, {"label": "fresh", "tier": "T2"},
                    {"tier": "T1"}, "fresh", None):
            self.assertNotIn("label", e.with_label(env, bad), bad)


class ToolsLabeled(unittest.TestCase):
    def test_age_label_from_the_envelope(self):
        self.assertEqual(tools.labeled(e.envelope(1, "measured", 3.7))["label"], T1)
        self.assertEqual(tools.labeled(e.envelope(1, "proxy", 51.3))["label"]["label"], "stale")
        self.assertEqual(tools.labeled(e.envelope(1, "imported", None))["label"]["label"], "missing")
        self.assertNotIn("label", tools.labeled(e.missing("nothing")))


class Handlers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name) / "st"
        shutil.copytree(FIX, self.st)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, name, args=None, state=None):
        env = {"LIMITLESS_STATE": str(state or self.st), "LIMITLESS_SCORECARD": str(CARD),
               "LIMITLESS_CONFIG": str(Path(self.tmp.name) / "none.json")}
        if name == "limitless_catchup":  # the catch-up needs to know when the person last wrote
            env["LIMITLESS_OWNER_DBS"] = str(owner_db(Path(self.tmp.name) / "owner.db"))
        with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=NOW):
            return json.loads(plugin._handler(plugin.TOOLS[name][1])(args or {}))

    def test_every_tool_keeps_the_envelope_and_labels_a_value(self):
        for name in plugin.TOOLS:
            if name in ("limitless_anki", "limitless_body", "limitless_overnight", "limitless_rides",
                        "limitless_sleep", "limitless_naps", "limitless_quiet", "limitless_blocks", "limitless_flow_metrics", "limitless_flow_ledger",
                        "limitless_propose", "limitless_loop", "limitless_presleep_hr",
                        "limitless_schedule", "limitless_habit_next", "limitless_ideas", "limitless_card_view"):  # own T1 words; the
                continue                     # fixture has no body_file, work queue, rides, sleep or AW data;
                                             # quiet: on, off, ...; anki: no collection;
                                             # propose: its action words; loop: no week decided;
                                             # presleep_hr: no pre-sleep file
                                             # schedule: its card count (test_schedule_tool)
                                             # habit_next: next habit: <name> (test_habit_next_tool)
                                             # card_view: a state card with <rows> (test_ui_card_tool)
            res = self.call(name, {"text": "a synthetic thought"})
            self.assertTrue(FIELDS <= set(res), (name, res))
            self.assertIsNotNone(res["value"], name)
            lab = res["label"]
            self.assertEqual(lab["tier"], "T1", name)
            self.assertIn(lab["label"], ("fresh", "stale", "missing", "unknown"), name)
            self.assertEqual(re.findall(r"\d", lab["label"]), [], name)

    def test_status_is_fresh_and_its_value_is_unchanged(self):
        res = self.call("limitless_status")
        self.assertEqual(res["label"], {"label": "fresh", "tier": "T1", "modality": "measured"})
        self.assertEqual(res["value"]["inputs"]["bike"], {"age_h": None, "state": "down"})

    def test_a_null_result_has_a_reason_and_no_label(self):
        res = self.call("limitless_status", state=Path(self.tmp.name) / "nowhere")
        self.assertIsNone(res["value"])
        self.assertIn("reason", res)
        self.assertNotIn("label", res)

    def test_state_items_carry_their_metric_label(self):
        items = self.call("limitless_state")["value"]["items"]
        self.assertEqual(items["sleep"]["label"]["label"], "short")
        self.assertEqual(items["readiness"]["label"]["label"], "low")


if __name__ == "__main__":
    unittest.main()
