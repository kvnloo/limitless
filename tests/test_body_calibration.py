"""body_calibration: pair reference scans with scale rows, fit the simplest model, correct the scale rows.

Synthetic rows only. A reference row has a method in ``body_reference_methods`` (default dxa); every other
row the scale wrote with ``calibrated: false`` is a scale row.
"""
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import body_calibration as bc  # noqa: E402

DAY0 = date(2030, 1, 1)


def scale(day, bf, calibrated=False, method="synthetic-scale"):
    return {"day": (DAY0 + timedelta(days=day)).isoformat(), "bf_pct": float(bf), "method": method,
            "calibrated": calibrated}


def ref(day, bf, method="dxa"):
    return {"day": (DAY0 + timedelta(days=day)).isoformat(), "bf_pct": float(bf), "method": method,
            "calibrated": True}


class Pairs(unittest.TestCase):
    def test_same_day_pairs_with_the_median_of_that_days_scale_rows(self):
        got = bc.pairs([scale(0, 20), scale(0, 22), ref(0, 25), scale(1, 30)])
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["reference"], got[0]["scale"], got[0]["gap_days"]), (25.0, 21.0, 0))

    def test_the_nearest_scale_day_wins(self):
        got = bc.pairs([scale(-3, 10), scale(2, 20), scale(-1, 30), ref(0, 25)])
        self.assertEqual([(p["scale"], p["gap_days"]) for p in got], [(30.0, 1)])

    def test_a_tie_takes_the_earlier_day(self):
        got = bc.pairs([scale(2, 20), scale(-2, 30), ref(0, 25)])
        self.assertEqual([(p["scale"], p["scale_day"]) for p in got], [(30.0, (DAY0 - timedelta(days=2)).isoformat())])

    def test_nothing_within_pair_days_is_no_pair(self):
        rows = [scale(-4, 20), scale(4, 20), ref(0, 25)]
        self.assertEqual(bc.pairs(rows), [])
        self.assertEqual(bc.PAIR_DAYS, 3)
        self.assertEqual(len(bc.pairs(rows, pair_days=4)), 1)
        self.assertEqual(bc.pairs([scale(1, 20), ref(0, 25)], pair_days=0), [])

    def test_reference_methods_are_configurable_and_case_blind(self):
        rows = [scale(0, 20), ref(0, 25, method="DXA"), ref(1, 26, method="synthetic-reference"), scale(1, 21)]
        self.assertEqual([p["reference"] for p in bc.pairs(rows)], [25.0])
        self.assertEqual([p["reference"] for p in bc.pairs(rows, methods=["synthetic-reference"])], [26.0])
        self.assertEqual(len(bc.pairs(rows, methods=["dxa", "Synthetic-Reference"])), 2)

    def test_rows_already_calibrated_are_not_scale_rows(self):
        self.assertEqual(bc.pairs([scale(0, 20, calibrated=True), ref(0, 25)]), [])

    def test_bad_input_is_no_pair(self):
        for rows in (None, "x", [None, {"day": "nope", "bf_pct": 1}], [ref(0, 25), {"day": "2030-01-01"}]):
            self.assertEqual(bc.pairs(rows), [], rows)


if __name__ == "__main__":
    unittest.main()
