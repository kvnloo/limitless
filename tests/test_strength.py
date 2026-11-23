"""strength.strength_of: how strong a claim is, on the person's evidential-strength ladder, in words.
measured > derived > association > preregistered > repeated > replicated. No score, no digit in the words.
Synthetic claims only."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import strength  # noqa: E402


def week(week_of, verdict="supports", locked=True, logged_days=5):
    return {"week_of": week_of, "locked": locked, "verdict": verdict, "logged_days": logged_days}


class Shape(unittest.TestCase):
    def assertRung(self, claim, rung):
        out = strength.strength_of(claim)
        self.assertEqual(set(out), {"rung", "words", "why"}, out)
        self.assertEqual(out["rung"], rung, out)
        self.assertEqual(re.findall(r"\d", out["words"]), [], out["words"])
        self.assertEqual(re.findall(r"\d", out["why"]), [], out["why"])
        if rung is not None:
            self.assertTrue(out["words"].startswith(rung + ": "), out["words"])
        return out


class Ladder(Shape):
    def test_the_order(self):
        self.assertEqual(strength.LADDER,
                         ("measured", "derived", "association", "preregistered", "repeated", "replicated"))

    def test_a_single_reading_is_measured(self):
        self.assertRung({"readings": 1}, "measured")

    def test_computed_from_readings_is_derived(self):
        self.assertRung({"readings": 4, "computed": True}, "derived")

    def test_nothing_has_no_rung(self):
        out = self.assertRung({}, None)
        self.assertTrue(out["words"])

    def test_not_a_dict_has_no_rung(self):
        self.assertRung(None, None)
        self.assertRung("this habit helps my sleep", None)


class Association(Shape):
    def test_co_occurrence_across_days_is_association(self):
        out = self.assertRung({"readings": 6, "computed": True, "days": 6}, "association")
        self.assertIn("no locked prediction", out["words"])

    def test_fewer_than_three_days_never_climb(self):
        self.assertRung({"readings": 2, "computed": True, "days": 2}, "derived")
        self.assertRung({"days": 2}, None)

    def test_a_count_that_is_not_a_whole_number_is_nothing(self):
        self.assertRung({"days": "many"}, None)
        self.assertRung({"days": True}, None)
        self.assertRung({"days": 4.0}, None)


class LockedWeeks(Shape):
    def test_one_supported_locked_week_is_preregistered(self):
        out = self.assertRung({"days": 7, "weeks": [week("2030-01-07")]}, "preregistered")
        self.assertEqual(out["words"], "preregistered: one locked week supported it")

    def test_two_separate_supported_weeks_are_repeated(self):
        out = self.assertRung({"weeks": [week("2030-01-07"), week("2030-01-21")]}, "repeated")
        self.assertEqual(out["words"], "repeated: two locked weeks supported it")
        out = self.assertRung({"weeks": [week(f"2030-0{m}-07") for m in range(1, 6)]}, "repeated")
        self.assertEqual(out["words"], "repeated: five locked weeks supported it")

    def test_the_same_week_twice_is_one_week(self):
        self.assertRung({"weeks": [week("2030-01-07"), week("2030-01-07")]}, "preregistered")

    def test_contradicted_and_inconclusive_never_climb(self):
        for verdict in ("contradicts", "inconclusive", "pending", None, "SUPPORTS "):
            with self.subTest(verdict=verdict):
                weeks = [week("2030-01-07", verdict), week("2030-01-14", verdict)]
                out = self.assertRung({"days": 14, "weeks": weeks}, "association")
                self.assertNotIn("supported", out["words"])

    def test_a_contradicted_week_beside_supported_ones_is_said(self):
        weeks = [week("2030-01-07"), week("2030-01-14", "contradicts")]
        out = self.assertRung({"weeks": weeks}, "preregistered")
        self.assertIn("one locked week did not", out["words"])
        self.assertEqual(self.assertRung({"weeks": weeks + [week("2030-01-21")]}, "repeated")["words"],
                         "repeated: two locked weeks supported it, one locked week did not")

    def test_an_unlocked_supports_never_climbs(self):
        self.assertRung({"weeks": [week("2030-01-07", locked=False), week("2030-01-14", locked=False)]}, None)

    def test_a_supported_week_with_fewer_than_three_logged_days_never_climbs(self):
        weeks = [week("2030-01-07", logged_days=2), week("2030-01-14", logged_days=2)]
        self.assertRung({"weeks": weeks}, None)
        self.assertRung({"weeks": [week("2030-01-07"), week("2030-01-14", logged_days=2)]}, "preregistered")


class Replicated(Shape):
    def test_an_external_citation_is_replicated(self):
        out = self.assertRung({"citation": "Synthetic Journal of Habits: a replicated trial"}, "replicated")
        self.assertIn("outside source", out["words"])

    def test_never_from_personal_data(self):
        weeks = [week(f"2030-{m:02d}-07") for m in range(1, 13)]
        out = self.assertRung({"readings": 99, "computed": True, "days": 365, "weeks": weeks}, "repeated")
        self.assertNotEqual(out["rung"], "replicated")
        for bad in ("", "   ", None, 7, ["a source"], {"title": "x"}):
            with self.subTest(citation=bad):
                self.assertRung({"weeks": weeks, "citation": bad}, "repeated")

    def test_a_rung_named_in_the_claim_is_ignored(self):
        self.assertRung({"rung": "replicated", "readings": 1}, "measured")


class Words(unittest.TestCase):
    def test_no_digit_in_any_words(self):
        claims = [{}, {"readings": 1}, {"readings": 3, "computed": True}, {"days": 30},
                  {"weeks": [week(f"2030-{m:02d}-07") for m in range(1, 13)]},
                  {"weeks": [week(f"2030-{m:02d}-07", "contradicts") for m in range(1, 13)] + [week("2031-01-07")]},
                  {"citation": "Synthetic source 2030, n=12"}]
        for c in claims:
            out = strength.strength_of(c)
            self.assertEqual(re.findall(r"\d", out["words"] + out["why"]), [], out)

    def test_no_score_key(self):
        out = strength.strength_of({"weeks": [week("2030-01-07")]})
        self.assertEqual(set(out), {"rung", "words", "why"})


if __name__ == "__main__":
    unittest.main()
