"""limitless_schedule: the schedule cards in plain words, read-only (raw fields only in ``value``)."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_plugin import FIX, NOW, FakeCtx, load_plugin, manifest_list  # noqa: E402

from limitless import jobs, schedule_cards, tier_audit, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NAME = "limitless_schedule"


def _digit_free(s):
    return isinstance(s, str) and not any(c.isdigit() for c in s)


class ScheduleTool(unittest.TestCase):
    def setUp(self):
        self.ctx = FakeCtx()
        load_plugin().register(self.ctx)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name) / "state"
        shutil.copytree(FIX, self.st)

    def call(self, env=None):
        env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.st / "no-config.json"), **(env or {})}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(time, "time", return_value=NOW):
            out = self.ctx.tools[NAME]["handler"]({}, task_id="t", session_id="s")
        return json.loads(out)

    def test_registered_and_in_the_manifest(self):
        self.assertIn(NAME, manifest_list("provides_tools"))
        schema = self.ctx.tools[NAME]["schema"]
        self.assertEqual(schema["name"], NAME)
        self.assertEqual(schema["parameters"]["properties"], {})
        self.assertIn("Read-only", schema["description"])

    def test_value_holds_the_raw_cards(self):
        res = self.call()
        self.assertTrue({"value", "modality", "age_h", "evidence_tier"} <= set(res), res)
        habit = StateReader(self.st).habit()
        self.assertEqual(res["value"]["cards"], schedule_cards.cards(habit=habit))
        self.assertEqual([c["id"] for c in res["value"]["cards"]], list(jobs.SPECS))
        self.assertEqual(res["modality"], "derived")
        self.assertIsNone(res["age_h"])

    def test_plain_words_outside_value_are_digit_free(self):
        res = self.call()
        self.assertEqual(res["label"], {"label": "six schedule cards, each on an event, none on a clock",
                                        "tier": "T1", "modality": "derived"})
        self.assertEqual(len(res["lines"]), len(jobs.SPECS))
        for s in [res["label"]["label"], *res["lines"]]:
            self.assertTrue(_digit_free(s), s)
        self.assertEqual(set(res) - {"value"}, {"modality", "age_h", "evidence_tier", "label", "lines"})
        self.assertTrue(res["lines"][0].startswith('Schedule "Wake-up brief" (when you wake up'))

    def test_an_external_job_says_who_sends_it(self):
        res = self.call({"LIMITLESS_EXTERNAL_JOBS": "wake_brief"})
        card = res["value"]["cards"][0]
        self.assertEqual(card["sender"], "external")
        self.assertTrue(res["lines"][0].endswith("; sent by its own sender, not by limitless-jobs"), res["lines"][0])
        self.assertFalse(res["lines"][1].endswith("not by limitless-jobs"))

    def test_the_words_go_through_tier_audit_gate(self):
        audit = Path(self.tmp.name) / "audit.jsonl"
        self.call({"LIMITLESS_AUDIT": str(audit)})
        rows = [json.loads(ln) for ln in audit.read_text().splitlines()]
        self.assertIn("tool:limitless_schedule", [r["hook"] for r in rows])
        self.assertTrue(all(r["tier"] == "T1" and not r["blocked"] for r in rows), rows)

    def test_a_digit_in_the_words_is_blocked_and_the_raw_cards_stay(self):
        bad = schedule_cards.cards()
        bad[0] = dict(bad[0], description="Schedule \"x\" (at 7): synthetic")
        with mock.patch.object(schedule_cards, "cards", return_value=bad):
            res = tools.schedule(StateReader(self.st), NOW, env={})
        self.assertNotIn("label", res)
        self.assertNotIn("lines", res)
        self.assertEqual(res["value"]["cards"], bad)
        self.assertTrue(_digit_free(res["reason"]), res["reason"])

    def test_read_only(self):
        before = sorted((p.name, p.stat().st_mtime_ns) for p in self.st.iterdir())
        self.call()
        self.assertEqual(sorted((p.name, p.stat().st_mtime_ns) for p in self.st.iterdir()), before)

    def test_no_state_still_lists_the_default_cards(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        res = self.call({"LIMITLESS_STATE": str(empty)})
        self.assertEqual(res["value"]["cards"], schedule_cards.cards())


if __name__ == "__main__":
    unittest.main()
