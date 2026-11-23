"""propose(state): one small next action from a readable rule table, NO_SUGGESTION by default.
Synthetic labels only."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import propose as p  # noqa: E402

NO = p.NO_SUGGESTION


class Default(unittest.TestCase):
    def test_empty_or_unknown_state_is_no_suggestion(self):
        for state in ({}, None, "peak", [], {"window": "unknown"}, {"asleep": None, "quiet": "unknown"}):
            r = p.propose(state)
            self.assertEqual(r["action"], NO, state)
            self.assertEqual(r["rule_id"], p.DEFAULT_ID, state)
            self.assertEqual(r["evidence"], [], state)

    def test_result_shape(self):
        self.assertEqual(set(p.propose({})), {"action", "because", "rule_id", "evidence"})


class Holds(unittest.TestCase):
    def test_asleep_is_no_suggestion(self):
        r = p.propose({"asleep": True, "habit_week": "running", "habit_today": "unlogged"})
        self.assertEqual((r["action"], r["rule_id"], r["evidence"]), (NO, "asleep", ["asleep"]))

    def test_quiet_held_is_no_suggestion(self):
        for q in ("off", "quiet tonight", "snoozed"):
            r = p.propose({"quiet": q, "habit_week": "running", "habit_today": "unlogged"})
            self.assertEqual((r["action"], r["rule_id"], r["evidence"]), (NO, "quiet", ["quiet"]), q)

    def test_quiet_on_does_not_hold(self):
        r = p.propose({"quiet": "on", "habit_week": "running", "habit_today": "unlogged"})
        self.assertNotEqual(r["rule_id"], "quiet")

    def test_focus_block_or_focused_mode_is_no_suggestion(self):
        r = p.propose({"focus_block": "in a block", "habit_week": "running", "habit_today": "unlogged"})
        self.assertEqual((r["action"], r["rule_id"], r["evidence"]), (NO, "focus-block", ["focus_block"]))
        r = p.propose({"mode": "focused", "habit_week": "running", "habit_today": "unlogged"})
        self.assertEqual((r["action"], r["rule_id"], r["evidence"]), (NO, "focused-mode", ["mode"]))

    def test_truthy_lookalikes_never_match(self):
        for v in (1, "yes", "True", "asleep"):
            self.assertNotEqual(p.propose({"asleep": v})["rule_id"], "asleep", v)


if __name__ == "__main__":
    unittest.main()
