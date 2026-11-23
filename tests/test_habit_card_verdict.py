"""habit_card.verdict_inputs(card_state, week_start, rule) -> what a Keep / Drop rule reads: the week number, the
rule id as given and the two decisions. The rule itself is the host's (limitless: stop_rule). Synthetic data only."""
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_card  # noqa: E402

START = date(2030, 1, 7)


def state(*answers):
    return {"checkins": {(START + timedelta(days=i)).isoformat(): a for i, a in enumerate(answers) if a}}


class VerdictInputs(unittest.TestCase):
    def test_the_inputs_are_the_week_number_the_rule_and_keep_or_drop(self):
        self.assertEqual(habit_card.verdict_inputs(state("Done", "No", None, "Done"), START, "most_done"),
                         {"done": 2, "logged": 3, "unknown": 4, "rule": "most_done", "decisions": ("Keep", "Drop")})
        self.assertEqual(habit_card.DECISIONS, ("Keep", "Drop"))

    def test_no_rule_is_passed_on_as_none(self):
        self.assertIsNone(habit_card.verdict_inputs(state("Done"), START)["rule"])

    def test_no_week_is_none(self):
        self.assertIsNone(habit_card.verdict_inputs(state("Done"), None, "most_done"))

    def test_it_decides_nothing(self):
        v = habit_card.verdict_inputs(state("No", "No", "No"), START, "most_done")
        self.assertFalse({"verdict", "keep", "drop", "score"} & set(v))


class Contract(unittest.TestCase):
    def test_the_contract_week_gives_the_same_three_numbers(self):
        s = {}
        for i, r in enumerate(("Done", "Done", None, "No", "Skip", None, "Done")):
            if r:
                s = habit_card.record(s, (START + timedelta(days=i)).isoformat(), r)
        v = habit_card.verdict_inputs(s, START, "most_done")
        self.assertEqual((v["done"], v["logged"], v["unknown"]), (3, 4, 3))


if __name__ == "__main__":
    unittest.main()
