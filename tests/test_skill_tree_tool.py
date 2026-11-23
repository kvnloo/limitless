"""limitless_skill_tree (read-only): the four layers and a state word per habit as one derived envelope with a
digit-free T1 label. Nothing is written, sent or started. Synthetic only."""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_catalogue, plugin, skill_tree, stop_rule, tools  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NOW = 1894708800.0
TODAY = date.fromtimestamp(NOW)
CAT = habit_catalogue.CATALOGUE
FIELDS = {"value", "modality", "age_h", "evidence_tier"}


def snapshot(d: Path) -> dict:
    return {str(f.relative_to(d)): (f.stat().st_mtime_ns, f.stat().st_size) for f in d.rglob("*") if f.is_file()}


class Words(unittest.TestCase):
    def test_label_names_the_last_open_layer_and_kept_in_words(self):
        self.assertEqual(skill_tree.label(skill_tree.tree(CAT, {})), "Foundation open, no habit kept")
        self.assertEqual(skill_tree.label(skill_tree.tree(CAT, {CAT[0]["id"]: "Keep"})),
                         "Learning open, one habit kept")
        self.assertEqual(skill_tree.label(skill_tree.tree(CAT, {CAT[0]["id"]: "Keep", CAT[1]["id"]: "Keep"})),
                         "Learning open, two habits kept")

    def test_lines_one_per_layer_digit_free(self):
        t = skill_tree.tree(CAT, {CAT[0]["id"]: "Keep", CAT[1]["id"]: "Drop"}, current=CAT[2]["name"])
        ls = skill_tree.lines(t)
        self.assertEqual(len(ls), len(skill_tree.LAYERS))
        self.assertTrue(ls[0].startswith("Foundation open: "), ls[0])
        self.assertIn(f"{CAT[0]['name']} kept", ls[0])
        self.assertIn(f"{CAT[1]['name']} dropped", ls[0])
        self.assertIn(f"{CAT[2]['name']} trying", ls[0])
        self.assertIn(f"{CAT[3]['name']} not tried", ls[0])
        self.assertTrue(ls[1].startswith("Learning open: "), ls[1])
        self.assertTrue(ls[2].startswith("Flow later"), ls[2])
        self.assertEqual(ls[3], "Enhancement later: no habits on the list yet")
        for ln in ls:
            self.assertEqual(re.findall(r"\d", ln), [], ln)


class Tool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name) / "st"
        self.st.mkdir()
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(Path(self.tmp.name) / "none.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, args=None):
        with mock.patch.dict(os.environ, self.env), mock.patch("time.time", return_value=NOW):
            return json.loads(plugin._handler(plugin.TOOLS["limitless_skill_tree"][1], "limitless_skill_tree")(args or {}))

    def decide(self, habit, decision, week_of="2030-01-08"):
        stop_rule.record_loop(self.st, {"habit": habit, "week_of": week_of, "checkins": {week_of: "Done"}},
                              decision, f"{week_of}T09:00:00+00:00", now=NOW)

    def test_registered_in_plugin_yaml_and_tools(self):
        self.assertIn("limitless_skill_tree", plugin.TOOLS)
        self.assertIn("  - limitless_skill_tree\n", (ROOT / "plugin.yaml").read_text())
        desc = plugin.TOOLS["limitless_skill_tree"][0]["description"]
        self.assertIn("Read-only", desc)
        self.assertIn("never", desc)

    def test_nothing_decided_foundation_open_and_tier_none(self):
        res = self.call()
        self.assertTrue(FIELDS <= set(res), res)
        self.assertEqual([layer["name"] for layer in res["value"]["layers"]], list(skill_tree.LAYERS))
        self.assertEqual([layer["open"] for layer in res["value"]["layers"]], [True, False, False, False])
        self.assertEqual(res["modality"], "derived")
        self.assertIsNone(res["age_h"])
        self.assertEqual(res["evidence_tier"], "none")
        self.assertEqual(res["label"], {"label": "Foundation open, no habit kept", "tier": "T1", "modality": "derived"})
        self.assertIn("never starts", res["note"])

    def test_the_loop_rows_and_the_running_week(self):
        self.decide(CAT[0]["name"], "Keep", "2030-01-01")
        self.decide(CAT[1]["name"], "Drop", "2030-01-08")
        (self.st / "habit.json").write_text(json.dumps({"habit": CAT[2]["name"], "week_of": TODAY.isoformat(),
                                                        "checkins": {}}))
        res = self.call()
        found = {h["name"]: h["state"] for layer in res["value"]["layers"] for h in layer["habits"]}
        self.assertEqual([found[CAT[i]["name"]] for i in range(4)], ["kept", "dropped", "trying", "not tried"])
        self.assertEqual(res["label"]["label"], "Learning open, one habit kept")
        self.assertEqual(res["evidence_tier"], "stale")      # self-reported decisions, days old

    def test_a_finished_week_is_not_trying(self):
        (self.st / "habit.json").write_text(json.dumps({"habit": CAT[0]["name"], "week_of": "2030-01-01",
                                                        "checkins": {}}))
        res = self.call()
        self.assertEqual(res["value"]["layers"][0]["habits"][0]["state"], "not tried")

    def test_a_torn_ledger_is_not_tried_never_dropped(self):
        (self.st / "predictions.jsonl").write_text('{"kind": "loop", "week_of": "2030-01-08", "habit": "'
                                                   + CAT[0]["name"] + '", "decision": "Dr\n[1, 2]\n')
        (self.st / "habit.json").write_text("{not json")
        res = self.call()
        states = {h["state"] for layer in res["value"]["layers"] for h in layer["habits"]}
        self.assertEqual(states, {"not tried"})

    def test_read_only_and_digit_free(self):
        self.decide(CAT[0]["name"], "Keep")
        before = snapshot(self.st)
        res = self.call()
        self.assertEqual(snapshot(self.st), before)
        words = json.dumps(res["value"]) + res["label"]["label"]
        self.assertEqual(re.findall(r"\d", words), [])
        for w in ("score", "level", "percent", "xp", "streak"):
            self.assertNotIn(w, words.lower())

    def test_tools_function_matches_the_core(self):
        self.decide(CAT[0]["name"], "Keep")
        res = tools.skill_tree(self.st, NOW, TODAY)
        rows = stop_rule.loop_rows(self.st)
        self.assertEqual(res["value"]["layers"], skill_tree.tree(CAT, rows))


if __name__ == "__main__":
    unittest.main()
