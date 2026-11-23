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


def paired(scales, refs, start=0, step=10):
    """Rows: scale reading and reference scan on the same day, every ``step`` days."""
    out = []
    for i, (s, r) in enumerate(zip(scales, refs)):
        out += [scale(start + i * step, s), ref(start + i * step, r)]
    return out


class Fit(unittest.TestCase):
    def test_two_pairs_fit_a_constant_offset(self):
        f = bc.fit(paired([20, 24], [23, 30]))
        self.assertEqual((f["model"], f["pairs"]), ("offset", 2))
        self.assertAlmostEqual(f["offset"], 4.5)                # median of 3 and 6
        self.assertIsNone(f["slope"])
        self.assertAlmostEqual(bc.predict(f, 30.0), 34.5)

    def test_the_offset_is_a_median_not_a_mean(self):
        f = bc.fit(paired([20, 21, 22], [23, 24, 35]))           # one wild pair
        self.assertAlmostEqual(f["offset"], 3.0)

    def test_one_pair_or_none_is_no_calibration_in_words(self):
        for rows in (paired([20], [23]), [scale(0, 20)], [], None, paired([20, 21], [23, 24], step=1)[:3]):
            f = bc.fit(rows)
            self.assertIsNone(f["model"], rows)
            self.assertIsNone(f["offset"])
            self.assertEqual(f["label"], {"label": "uncalibrated: fewer than two reference scans paired with a "
                                                   "scale reading", "tier": "T1"})
            self.assertIs(bc.predict(f, 20.0), None)
        self.assertEqual(bc.fit(paired([20], [23]))["pairs"], 1)

    def test_a_fit_says_so_in_words(self):
        self.assertEqual(bc.fit(paired([20, 24], [23, 29]))["label"],
                         {"label": "calibrated against reference scans", "tier": "T1"})

    def test_never_a_slope_from_fewer_than_five_pairs(self):
        # a perfect line (reference = one and a half times the scale, minus seven) on four pairs: still an offset
        f = bc.fit(paired([16, 18, 20, 22], [17, 20, 23, 26]))
        self.assertEqual((f["model"], f["slope"]), ("offset", None))
        self.assertIsNone(f["loo_linear"])
        self.assertEqual(bc.MIN_LINEAR_PAIRS, 5)

    def test_five_pairs_take_the_line_when_it_beats_the_offset_leave_one_out(self):
        f = bc.fit(paired([16, 18, 20, 22, 24], [17, 20, 23, 26, 29]))
        self.assertEqual(f["model"], "linear")
        self.assertAlmostEqual(f["slope"], 1.5)
        self.assertAlmostEqual(f["intercept"], -7.0)
        self.assertLess(f["loo_linear"], f["loo_offset"])
        self.assertAlmostEqual(bc.predict(f, 30.0), 38.0)
        self.assertAlmostEqual(f["offset"], 3.0)                # the offset is still reported (median of one to five)

    def test_five_pairs_keep_the_offset_when_the_line_does_not_beat_it(self):
        # reference = scale + three, with small noise: the line's leave-one-out error is not lower
        f = bc.fit(paired([20, 22, 24, 26, 28], [23.5, 24.5, 27.4, 28.6, 31.0]))
        self.assertEqual(f["model"], "offset")
        self.assertIsNotNone(f["loo_linear"])
        self.assertGreaterEqual(f["loo_linear"], f["loo_offset"])
        self.assertIsNone(f["slope"])
        self.assertAlmostEqual(bc.predict(f, 30.0), 33.0)

    def test_a_flat_scale_cannot_carry_a_line(self):
        f = bc.fit(paired([20] * 5, [21, 22, 23, 24, 25]))
        self.assertEqual(f["model"], "offset")
        self.assertIsNone(f["loo_linear"])

    def test_fit_passes_methods_and_pair_days_through(self):
        rows = [scale(0, 20), ref(2, 24, "synthetic-reference"), scale(20, 22), ref(22, 25, "synthetic-reference")]
        self.assertIsNone(bc.fit(rows)["model"])
        self.assertIsNone(bc.fit(rows, methods=["synthetic-reference"], pair_days=1)["model"])
        f = bc.fit(rows, methods=["synthetic-reference"])
        self.assertEqual((f["model"], f["pairs"]), ("offset", 2))
        self.assertAlmostEqual(f["offset"], 3.5)


if __name__ == "__main__":
    unittest.main()
