"""habit_catalogue.next_habit: the first catalogue habit not kept and not running; a dropped one comes back
only after every other one was tried; None with a plain reason when the list is exhausted.

Loop rows are the shape stop_rule.record_loop writes to predictions.jsonl. Synthetic only.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from limitless import habit_catalogue, stop_rule  # noqa: E402

CAT = habit_catalogue.CATALOGUE
WEEKS = ["2030-01-%02d" % d for d in range(1, 29, 7)] + ["2030-02-%02d" % d for d in range(1, 29, 7)] + \
        ["2030-03-%02d" % d for d in range(1, 29, 7)]


def row(i, habit, decision):
    return {"kind": "loop", "week_of": WEEKS[i], "habit": habit, "decision": decision}


def rows(*pairs):
    return [row(i, h, d) for i, (h, d) in enumerate(pairs)]


class NextHabit(unittest.TestCase):
    def test_before_the_first_week_the_first_entry(self):
        n = habit_catalogue.next_habit([])
        self.assertIs(n.habit, CAT[0])
        self.assertTrue(n.reason)
        self.assertIs(habit_catalogue.next_habit(None).habit, CAT[0])

    def test_kept_habits_are_never_offered_again(self):
        n = habit_catalogue.next_habit(rows((CAT[0]["name"], "Keep")))
        self.assertIs(n.habit, CAT[1])

    def test_a_running_habit_is_not_offered(self):
        self.assertIs(habit_catalogue.next_habit([], current=CAT[0]["name"]).habit, CAT[1])
        self.assertIs(habit_catalogue.next_habit([], current={"habit": CAT[0]["name"]}).habit, CAT[1])
        self.assertIs(habit_catalogue.next_habit([], current=CAT[1]["id"]).habit, CAT[0])

    def test_a_dropped_habit_waits_until_every_other_was_tried(self):
        n = habit_catalogue.next_habit(rows((CAT[0]["name"], "Drop")))
        self.assertIs(n.habit, CAT[1])
        tried = [(h["name"], "Drop") for h in CAT[1:]] + [(CAT[0]["name"], "Drop")]
        # all dropped: the first dropped in catalogue order comes back
        n = habit_catalogue.next_habit(rows(*tried))
        self.assertIs(n.habit, CAT[0])
        self.assertIn("tried", n.reason)

    def test_a_dropped_habit_comes_back_only_when_none_is_untried(self):
        tried = [(h["name"], "Drop") for h in CAT[:-1]]
        self.assertIs(habit_catalogue.next_habit(rows(*tried)).habit, CAT[-1])

    def test_kept_wins_over_an_earlier_drop(self):
        n = habit_catalogue.next_habit(rows((CAT[0]["name"], "Drop"), (CAT[0]["name"], "Keep")))
        self.assertIs(n.habit, CAT[1])

    def test_exhausted_list_is_none_with_a_plain_reason(self):
        n = habit_catalogue.next_habit(rows(*[(h["name"], "Keep") for h in CAT]))
        self.assertIsNone(n.habit)
        self.assertTrue(n.reason)
        self.assertFalse(any(c.isdigit() for c in n.reason))
        # every one kept but the running one: nothing else to offer
        kept = [(h["name"], "Keep") for h in CAT[:-1]]
        n = habit_catalogue.next_habit(rows(*kept), current=CAT[-1]["name"])
        self.assertIsNone(n.habit)

    def test_a_week_without_a_loop_row_is_not_a_drop(self):
        # a skipped or undecided week writes no loop row: the habit is still untried, so it is first again
        self.assertIs(habit_catalogue.next_habit([]).habit, CAT[0])
        undecided = [{"kind": "loop", "week_of": WEEKS[0], "habit": CAT[0]["name"], "decision": None}]
        self.assertIs(habit_catalogue.next_habit(undecided).habit, CAT[0])

    def test_unknown_habits_and_odd_rows_are_ignored(self):
        odd = [{"kind": "loop", "week_of": WEEKS[0], "habit": "Synthetic habit", "decision": "Keep"},
               {"kind": "prediction", "week_of": WEEKS[1], "habit": CAT[0]["name"], "decision": "Keep"},
               "not a row", None, {"kind": "loop", "habit": None, "decision": "Drop"}]
        self.assertIs(habit_catalogue.next_habit(odd).habit, CAT[0])

    def test_names_match_in_any_case(self):
        n = habit_catalogue.next_habit(rows(("  feeds-free FIRST hour", "Keep")))
        self.assertIs(n.habit, CAT[1])

    def test_reasons_are_digit_free(self):
        for rs in ([], rows((CAT[0]["name"], "Drop")), rows(*[(h["name"], "Drop") for h in CAT])):
            self.assertFalse(any(c.isdigit() for c in habit_catalogue.next_habit(rs).reason))

    def test_reads_the_real_loop_rows(self):
        with tempfile.TemporaryDirectory() as d:
            stop_rule.record_loop(d, {"habit": CAT[0]["name"], "week_of": "2030-01-08",
                                      "checkins": {"2030-01-08": "No"}}, "Drop", "2030-01-14T09:00:00+00:00",
                                  now=1894708800.0)
            n = habit_catalogue.next_habit(stop_rule.loop_rows(d))
            self.assertIs(n.habit, CAT[1])


if __name__ == "__main__":
    unittest.main()
