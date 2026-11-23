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


if __name__ == "__main__":
    unittest.main()
