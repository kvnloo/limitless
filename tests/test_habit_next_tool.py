"""limitless_habit_next (read-only): the next habit from the catalogue as one derived envelope with a
digit-free T1 label. It only suggests: nothing is written or sent, and no habit week starts. Synthetic only."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_catalogue, plugin, stop_rule, tools  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state"
NOW = 1894708800.0
TODAY = date.fromtimestamp(NOW)
CAT = habit_catalogue.CATALOGUE
FIELDS = {"value", "modality", "age_h", "evidence_tier"}


def snapshot(d: Path) -> dict:
    return {str(f.relative_to(d)): (f.stat().st_mtime_ns, f.stat().st_size) for f in d.rglob("*") if f.is_file()}


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
            return json.loads(plugin._handler(plugin.TOOLS["limitless_habit_next"][1], "limitless_habit_next")(args or {}))

    def decide(self, habit, decision, week_of="2030-01-08"):
        stop_rule.record_loop(self.st, {"habit": habit, "week_of": week_of, "checkins": {week_of: "Done"}},
                              decision, f"{week_of}T09:00:00+00:00", now=NOW)

    def test_registered_in_plugin_yaml_and_tools(self):
        self.assertIn("limitless_habit_next", plugin.TOOLS)
        self.assertIn("  - limitless_habit_next\n", (ROOT / "plugin.yaml").read_text())
        desc = plugin.TOOLS["limitless_habit_next"][0]["description"]
        self.assertIn("start habit", desc)
        self.assertIn("Read-only", desc)

    def test_before_the_first_week_the_first_habit(self):
        res = self.call()
        self.assertTrue(FIELDS <= set(res), res)
        self.assertEqual(res["value"], {k: CAT[0][k] for k in ("id", "name", "cue", "start")})
        self.assertEqual(res["modality"], "derived")
        self.assertIsNone(res["age_h"])
        self.assertEqual(res["evidence_tier"], "none")      # no decided week: nothing but the list's order
        self.assertEqual(res["label"], {"label": f"next habit: {CAT[0]['name']}", "tier": "T1", "modality": "derived"})
        self.assertIn("start habit", res["note"])
        self.assertEqual(res["habit_week"], "not running")

    def test_after_a_drop_the_next_one(self):
        self.decide(CAT[0]["name"], "Drop")
        res = self.call()
        self.assertEqual(res["value"]["id"], CAT[1]["id"])
        self.assertEqual(res["evidence_tier"], "stale")     # the decision is self-reported, days old

    def test_a_running_week_is_not_offered_again(self):
        (self.st / "habit.json").write_text(json.dumps({"habit": CAT[0]["name"], "week_of": TODAY.isoformat(),
                                                        "checkins": {}}))
        res = self.call()
        self.assertEqual(res["value"]["id"], CAT[1]["id"])
        self.assertEqual(res["habit_week"], "running")

    def test_a_finished_week_is_not_the_current_one(self):
        (self.st / "habit.json").write_text(json.dumps({"habit": CAT[0]["name"], "week_of": "2030-01-01",
                                                        "checkins": {}}))
        self.assertEqual(self.call()["value"]["id"], CAT[0]["id"])   # never decided: still untried

    def test_exhausted_is_null_with_a_reason(self):
        for i, h in enumerate(CAT):
            self.decide(h["name"], "Keep", week_of=date.fromordinal(TODAY.toordinal() - 7 * (len(CAT) - i)).isoformat())
        res = self.call()
        self.assertIsNone(res["value"])
        self.assertEqual(res["evidence_tier"], "none")
        self.assertEqual(res["reason"], habit_catalogue.EXHAUSTED)

    def test_label_and_reasons_are_digit_free(self):
        for setup in (lambda: None, lambda: self.decide(CAT[0]["name"], "Drop")):
            setup()
            res = self.call()
            for w in (res["label"]["label"], res["because"], res["note"]):
                self.assertFalse(any(c.isdigit() for c in w), w)

    def test_read_only(self):
        shutil.copytree(FIX, self.st, dirs_exist_ok=True)
        self.decide(CAT[0]["name"], "Drop")
        before = snapshot(self.st)
        res = self.call()
        self.assertIsNotNone(res["value"])
        self.assertEqual(snapshot(self.st), before)

    def test_the_label_is_audited(self):
        log = Path(self.tmp.name) / "audit.jsonl"
        self.env["LIMITLESS_AUDIT"] = str(log)
        self.call()
        row = json.loads(log.read_text().splitlines()[-1])
        self.assertEqual((row["hook"], row["tier"], row["blocked"]), ("tool:limitless_habit_next", "T1", False))

    def test_tools_function_matches_the_handler(self):
        res = tools.habit_next(self.st, NOW, TODAY)
        self.assertEqual(res["value"]["id"], CAT[0]["id"])


if __name__ == "__main__":
    unittest.main()
