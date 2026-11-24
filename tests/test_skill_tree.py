"""skill_tree.tree: the Training Facility's four stacked layers, one state word per habit, words only.
Synthetic only: no real person's records."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_catalogue, skill_tree  # noqa: E402

CAT = habit_catalogue.CATALOGUE
FOUNDATION = [h for h in CAT if h["layer"] == "foundation"]
LEARNING = [h for h in CAT if h["layer"] == "learning"]
FLOW = [h for h in CAT if h["layer"] == "flow"]


def states(t):
    return {h["name"]: h["state"] for layer in t for h in layer["habits"]}


class Tree(unittest.TestCase):
    def test_four_layers_in_order_foundation_first(self):
        t = skill_tree.tree(CAT, {})
        self.assertEqual([layer["name"] for layer in t], ["Foundation", "Learning", "Flow", "Enhancement"])
        self.assertEqual([h["name"] for h in t[0]["habits"]], [h["name"] for h in FOUNDATION])
        self.assertEqual([h["name"] for h in t[1]["habits"]], [h["name"] for h in LEARNING])
        self.assertEqual([h["name"] for h in t[2]["habits"]], [h["name"] for h in FLOW])
        self.assertEqual(t[3]["habits"], [])            # nothing on the list for it yet

    def test_each_layer_and_habit_has_only_its_fields(self):
        for layer in skill_tree.tree(CAT, {}):
            self.assertEqual(set(layer), {"name", "open", "habits"})
            self.assertIs(type(layer["open"]), bool)
            for h in layer["habits"]:
                self.assertEqual(set(h), {"name", "state"})

    def test_nothing_decided_everything_not_tried_only_foundation_open(self):
        t = skill_tree.tree(CAT, {})
        self.assertEqual(set(states(t).values()), {"not tried"})
        self.assertEqual([layer["open"] for layer in t], [True, False, False, False])

    def test_keep_drop_and_this_weeks_habit(self):
        d = {FOUNDATION[0]["id"]: "Keep", FOUNDATION[1]["id"]: "Drop"}
        s = states(skill_tree.tree(CAT, d, current=FOUNDATION[2]["name"]))
        self.assertEqual(s[FOUNDATION[0]["name"]], "kept")
        self.assertEqual(s[FOUNDATION[1]["name"]], "dropped")
        self.assertEqual(s[FOUNDATION[2]["name"]], "trying")
        self.assertEqual(s[FOUNDATION[3]["name"]], "not tried")

    def test_a_dropped_habit_tried_again_is_trying(self):
        s = states(skill_tree.tree(CAT, {FOUNDATION[1]["id"]: "Drop"}, current=FOUNDATION[1]["name"]))
        self.assertEqual(s[FOUNDATION[1]["name"]], "trying")

    def test_current_may_be_habit_json(self):
        s = states(skill_tree.tree(CAT, {}, current={"habit": FOUNDATION[0]["name"], "week_of": "2030-01-08"}))
        self.assertEqual(s[FOUNDATION[0]["name"]], "trying")

    def test_a_layer_opens_when_every_earlier_layer_has_a_kept_habit(self):
        t = skill_tree.tree(CAT, {FOUNDATION[3]["id"]: "Keep"})
        self.assertEqual([layer["open"] for layer in t], [True, True, False, False])
        t = skill_tree.tree(CAT, {FOUNDATION[0]["id"]: "Keep", LEARNING[0]["id"]: "Keep"})
        self.assertEqual([layer["open"] for layer in t], [True, True, True, False])
        t = skill_tree.tree(CAT, {FOUNDATION[0]["id"]: "Keep", LEARNING[0]["id"]: "Keep", FLOW[0]["id"]: "Keep"})
        self.assertEqual([layer["open"] for layer in t], [True, True, True, True])

    def test_a_kept_later_habit_does_not_open_a_layer_past_an_unkept_one(self):
        t = skill_tree.tree(CAT, {LEARNING[0]["id"]: "Keep", FLOW[0]["id"]: "Keep"})
        self.assertEqual([layer["open"] for layer in t], [True, False, False, False])
        self.assertEqual(states(t)[LEARNING[0]["name"]], "kept")   # still said as it is

    def test_trying_or_dropped_does_not_open_the_next_layer(self):
        t = skill_tree.tree(CAT, {FOUNDATION[0]["id"]: "Drop"}, current=FOUNDATION[1]["name"])
        self.assertEqual([layer["open"] for layer in t], [True, False, False, False])

    def test_decisions_by_name_any_case(self):
        s = states(skill_tree.tree(CAT, {FOUNDATION[0]["name"].upper(): "Keep"}))
        self.assertEqual(s[FOUNDATION[0]["name"]], "kept")

    def test_loop_rows_are_read_as_decisions(self):
        rows = [{"kind": "loop", "week_of": "2030-01-01", "habit": FOUNDATION[0]["name"], "decision": "Drop"},
                {"kind": "loop", "week_of": "2030-01-08", "habit": FOUNDATION[0]["name"], "decision": "Keep"}]
        self.assertEqual(states(skill_tree.tree(CAT, rows))[FOUNDATION[0]["name"]], "kept")   # the latest wins

    def test_unknown_or_unreadable_records_are_not_tried_never_dropped(self):
        for d in (None, "garbage", 7, {FOUNDATION[0]["id"]: "maybe"}, {FOUNDATION[0]["id"]: None},
                  {"not_on_the_list": "Drop"}, {None: "Keep"},
                  [{"kind": "loop", "habit": FOUNDATION[0]["name"], "decision": "skip"}, "torn", None, 3],
                  [{"kind": "receipt", "habit": FOUNDATION[0]["name"], "decision": "Drop"}]):
            t = skill_tree.tree(CAT, d)
            self.assertEqual(set(states(t).values()), {"not tried"}, d)
            self.assertEqual([layer["open"] for layer in t], [True, False, False, False], d)

    def test_an_unknown_current_habit_is_nobodys_trying(self):
        for cur in (None, "", "Something not on the list", {"habit": 5}, ["x"]):
            self.assertNotIn("trying", states(skill_tree.tree(CAT, {}, current=cur)).values(), cur)

    def test_a_bad_catalogue_entry_is_skipped(self):
        cat = list(CAT) + [None, "x", {"layer": "foundation"}, {"name": "Odd", "layer": "elsewhere"}]
        t = skill_tree.tree(cat, {})
        self.assertEqual(sum(len(layer["habits"]) for layer in t), len(CAT))

    def test_an_enhancement_entry_lands_in_its_layer(self):
        cat = list(CAT) + [{"id": "synthetic_enh", "layer": "enhancement", "name": "A synthetic extra"}]
        t = skill_tree.tree(cat, {})
        self.assertEqual(t[3]["habits"], [{"name": "A synthetic extra", "state": "not tried"}])

    def test_words_only_no_score_level_percent_xp_or_streak(self):
        d = {FOUNDATION[0]["id"]: "Keep", LEARNING[0]["id"]: "Keep", FLOW[0]["id"]: "Drop"}
        t = skill_tree.tree(CAT, d, current=FOUNDATION[1]["name"])
        text = repr(t).lower()
        self.assertEqual(re.findall(r"\d", text), [])
        for word in ("score", "level", "percent", "xp", "streak", "points", "rank"):
            self.assertNotIn(word, text)
        self.assertLessEqual(set(states(t).values()), set(skill_tree.STATES))

    def test_pure_the_inputs_are_not_changed(self):
        d = {FOUNDATION[0]["id"]: "Keep"}
        skill_tree.tree(CAT, d)
        self.assertEqual(d, {FOUNDATION[0]["id"]: "Keep"})


if __name__ == "__main__":
    unittest.main()
