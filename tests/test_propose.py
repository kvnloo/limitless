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


class Suggestions(unittest.TestCase):
    def test_peak_open_and_a_peak_ask_waiting(self):
        r = p.propose({"post_wake_peak": "open", "peak_ask": "waiting"})
        self.assertEqual((r["action"], r["rule_id"], r["evidence"]),
                         ("decide the one waiting ask", "peak-ask", ["post_wake_peak", "peak_ask"]))

    def test_peak_ask_needs_both(self):
        for st in ({"post_wake_peak": "open"}, {"peak_ask": "waiting"},
                   {"post_wake_peak": "in use", "peak_ask": "waiting"},
                   {"post_wake_peak": "open", "peak_ask": "spent"}):
            self.assertEqual(p.propose(st)["action"], NO, st)

    def test_trough_and_anki_set(self):
        r = p.propose({"window": "trough", "anki": "set"})
        self.assertEqual((r["action"], r["rule_id"], r["evidence"]),
                         ("a short Anki review", "anki-trough", ["window", "anki"]))
        for st in ({"window": "peak", "anki": "set"}, {"window": "trough", "anki": "not set"}, {"anki": "set"}):
            self.assertEqual(p.propose(st)["action"], NO, st)

    def test_habit_week_running_and_today_unanswered(self):
        r = p.propose({"habit_week": "running", "habit_today": "unlogged"})
        self.assertEqual((r["action"], r["rule_id"], r["evidence"]),
                         ("answer today's habit check-in", "habit-checkin", ["habit_week", "habit_today"]))
        for today in ("Done", "No", "Skipped", None, "unknown"):
            st = {"habit_week": "running", "habit_today": today}
            self.assertEqual(p.propose(st)["action"], NO, st)
        self.assertEqual(p.propose({"habit_week": "not running", "habit_today": "unlogged"})["action"], NO)

    def test_first_match_wins_in_table_order(self):
        every = {"post_wake_peak": "open", "peak_ask": "waiting", "window": "trough", "anki": "set",
                 "habit_week": "running", "habit_today": "unlogged"}
        self.assertEqual(p.propose(every)["rule_id"], "peak-ask")
        self.assertEqual(p.propose(dict(every, peak_ask="none"))["rule_id"], "anki-trough")
        self.assertEqual(p.propose(dict(every, peak_ask="none", anki="not set"))["rule_id"], "habit-checkin")
        for hold, v in (("asleep", True), ("quiet", "off"), ("focus_block", "in a block"), ("mode", "focused")):
            self.assertEqual(p.propose(dict(every, **{hold: v}))["action"], NO, hold)


if __name__ == "__main__":
    unittest.main()
