"""propose(state): one small next action from a readable rule table, NO_SUGGESTION by default.
Synthetic labels only."""
import itertools
import os
import re
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

    def test_trough_and_a_palace_link_set_with_no_anki(self):
        r = p.propose({"window": "trough", "anki": "not set", "palace": "set"})
        self.assertEqual((r["action"], r["rule_id"], r["evidence"]),
                         ("a short memory palace walk", "palace-trough", ["window", "anki", "palace"]))
        for st in ({"window": "peak", "anki": "not set", "palace": "set"},
                   {"window": "trough", "anki": "not set", "palace": "not set"},
                   {"window": "trough", "anki": None, "palace": "set"},        # Anki unknown: never triggers
                   {"window": "trough", "anki": "not set", "palace": None},
                   {"window": None, "anki": "not set", "palace": "set"},
                   {"anki": "not set", "palace": "set"}):
            self.assertEqual(p.propose(st)["action"], NO, st)

    def test_the_anki_rule_comes_first_one_learning_offer_per_trough(self):
        r = p.propose({"window": "trough", "anki": "set", "palace": "set"})
        self.assertEqual(r["rule_id"], "anki-trough")
        ids = [x["id"] for x in p.RULES]
        self.assertEqual(ids.index("palace-trough"), ids.index("anki-trough") + 1)

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
        self.assertEqual(p.propose(dict(every, peak_ask="none", anki="not set", palace="set"))["rule_id"],
                         "palace-trough")
        for hold, v in (("asleep", True), ("quiet", "off"), ("focus_block", "in a block"), ("mode", "focused")):
            self.assertEqual(p.propose(dict(every, **{hold: v}))["action"], NO, hold)


BANNED = re.compile(r"(?i)\b(must|should|streak|missed|failed)\b")
CLOCK = re.compile(r"(?i)\d|\b(o'clock|noon|midnight|a\.m\.|p\.m\.|hours?|minutes?)\b")


def grid():
    """Every combination of each label's known values plus unknown (None)."""
    keys = sorted(p.STATE_KEYS)
    for combo in itertools.product(*[p.STATE_KEYS[k] + (None,) for k in keys]):
        yield dict(zip(keys, combo))


class Total(unittest.TestCase):
    def test_every_rule_reads_known_labels_and_values(self):
        for rule in p.RULES:
            self.assertEqual(set(rule), {"id", "when", "action", "because"}, rule["id"])
            self.assertIn(rule["action"], p.ACTIONS, rule["id"])
            for k, allowed in rule["when"].items():
                self.assertIn(k, p.STATE_KEYS, rule["id"])
                self.assertTrue(set(allowed) <= set(p.STATE_KEYS[k]), rule["id"])
        ids = [r["id"] for r in p.RULES] + [p.DEFAULT_ID]
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_table_is_total_over_a_synthetic_grid(self):
        seen, n = set(), 0
        ids = {r["id"] for r in p.RULES} | {p.DEFAULT_ID}
        for state in grid():
            r = p.propose(state)
            n += 1
            self.assertIn(r["action"], p.ACTIONS, state)
            self.assertIn(r["rule_id"], ids, state)
            self.assertTrue(set(r["evidence"]) <= set(state), state)
            seen.add(r["rule_id"])
        self.assertGreater(n, 1000)
        self.assertEqual(seen, ids)   # every rule is reachable

    def test_all_unknown_is_no_suggestion(self):
        self.assertEqual(p.propose({k: None for k in p.STATE_KEYS})["action"], p.NO_SUGGESTION)
        self.assertEqual(p.propose({k: "unknown" for k in p.STATE_KEYS})["action"], p.NO_SUGGESTION)


class Words(unittest.TestCase):
    def texts(self):
        yield p.DEFAULT_BECAUSE
        yield p.DEFAULT_ID
        for rule in p.RULES:
            yield rule["id"]
            yield rule["action"]
            yield rule["because"]

    def test_no_digit_clock_time_or_judging_word_in_any_text(self):
        for t in self.texts():
            self.assertIsNone(CLOCK.search(t), t)
            self.assertIsNone(BANNED.search(t), t)

    def test_no_digit_clock_time_or_judging_word_in_any_output(self):
        for state in itertools.islice(grid(), 0, None, 7):
            out = repr(p.propose(state))
            self.assertIsNone(CLOCK.search(out), state)
            self.assertIsNone(BANNED.search(out), state)

    def test_because_cites_the_labels(self):
        for rule in p.RULES:
            for k in rule["when"]:
                self.assertIn(p.LABEL_WORDS[k], rule["because"], (rule["id"], k))


if __name__ == "__main__":
    unittest.main()
