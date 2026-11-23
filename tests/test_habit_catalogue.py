"""habit_catalogue: a short, fixed, ordered list of habits for one habit a week. Foundation first, easiest first.

Synthetic only: no person's data. The list is code; these tests pin its shape and its words.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from limitless import habit_catalogue, jobs  # noqa: E402

FIELDS = {"id", "layer", "name", "cue", "start", "environment"}
# A clock time in any common spelling, and the words of a schedule by the clock.
CLOCK = re.compile(r"(?i)\b(\d{1,2}\s*(:\s*\d{2})?\s*(am|pm|a\.m\.|p\.m\.|h)\b|o'?clock|noon|midnight|"
                   r"half past|quarter (past|to)|in the morning|at night|tonight|every day at)\b")
# Drug, supplement, caffeine and dosing words: none belongs in a habit list.
SUBSTANCE = re.compile(r"(?i)\b(caffeine|coffee|espresso|tea|energy drink|drug|drugs|supplement|supplements|"
                       r"melatonin|magnesium|vitamin|pill|pills|tablet|capsule|dose|doses|dosing|dosage|mg|"
                       r"milligram|milligrams|medication|medicine|nicotine|alcohol|stimulant|nootropic|"
                       r"modafinil|adderall|microdose)\b")


def words(entry):
    return [v for v in entry.values() if isinstance(v, str)]


class Catalogue(unittest.TestCase):
    def test_short_fixed_and_ordered(self):
        cat = habit_catalogue.CATALOGUE
        self.assertIsInstance(cat, tuple)
        self.assertTrue(1 <= len(cat) <= 8, len(cat))
        layers = [h["layer"] for h in cat]
        self.assertEqual(layers, sorted(layers, key=habit_catalogue.LAYERS.index), "foundation first")
        self.assertEqual(habit_catalogue.LAYERS, ("foundation", "learning", "flow"))
        self.assertEqual(cat[0]["layer"], "foundation")

    def test_every_entry_has_the_fields(self):
        for h in habit_catalogue.CATALOGUE:
            self.assertEqual(set(h), FIELDS, h)
            self.assertIn(h["layer"], habit_catalogue.LAYERS, h)
            for k in ("id", "name", "cue", "start"):
                self.assertIsInstance(h[k], str, (k, h))
                self.assertTrue(h[k].strip(), (k, h))
            self.assertTrue(h["environment"] is None or (isinstance(h["environment"], str) and h["environment"].strip()))
            self.assertRegex(h["id"], r"^[a-z_]+$")

    def test_ids_and_names_are_unique(self):
        cat = habit_catalogue.CATALOGUE
        self.assertEqual(len({h["id"] for h in cat}), len(cat))
        self.assertEqual(len({h["name"].lower() for h in cat}), len(cat))

    def test_first_entry_is_the_existing_week_one_habit_with_its_cue(self):
        first = habit_catalogue.CATALOGUE[0]
        self.assertEqual(first["name"], "Feeds-free first hour")
        self.assertEqual(first["cue"], jobs.HABIT_CHECKIN.trigger_event)   # habit_cue: an hour after the wake

    def test_every_cue_is_an_event_never_a_clock_time(self):
        for h in habit_catalogue.CATALOGUE:
            self.assertIn(h["cue"], jobs.EVENTS, h)

    def test_no_digit_no_clock_time_no_substance_word(self):
        for h in habit_catalogue.CATALOGUE:
            for w in words(h):
                self.assertFalse(any(c.isdigit() for c in w), (h["id"], w))
                self.assertIsNone(CLOCK.search(w), (h["id"], w))
                self.assertIsNone(SUBSTANCE.search(w), (h["id"], w))

    def test_check_catches_what_it_should(self):
        self.assertEqual(habit_catalogue.problems(habit_catalogue.CATALOGUE), [])
        bad = dict(habit_catalogue.CATALOGUE[0], id="bad", name="Lights down by ten", cue="evening",
                   start="take one magnesium pill at 9pm")
        found = " ".join(habit_catalogue.problems((bad,)))
        for why in ("cue", "clock", "substance"):
            self.assertIn(why, found)
        self.assertIn("digit", " ".join(habit_catalogue.problems((dict(bad, start="walk for 2 minutes"),))))

    def test_entries_cannot_be_changed_in_place(self):
        with self.assertRaises(TypeError):
            habit_catalogue.CATALOGUE[0]["name"] = "something else"

    def test_by_name_and_id(self):
        first = habit_catalogue.CATALOGUE[0]
        self.assertIs(habit_catalogue.find(first["id"]), first)
        self.assertIs(habit_catalogue.find("  feeds-free FIRST hour "), first)
        self.assertIsNone(habit_catalogue.find("Synthetic habit"))
        self.assertIsNone(habit_catalogue.find(None))


if __name__ == "__main__":
    unittest.main()
