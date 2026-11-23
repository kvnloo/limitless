"""body.trend: the median of the last 14 days against the 14 before, as digit-free T1 words.

Synthetic rows only. Windows: recent = today and the 13 days before; prior = the 14 days before that.
"""
import json
import os
import random
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import body  # noqa: E402

TODAY = date(2030, 1, 28)


def row(days_ago, bf, calibrated=True, method="synthetic-scale"):
    return {"day": (TODAY - timedelta(days=days_ago)).isoformat(), "bf_pct": float(bf), "method": method,
            "calibrated": calibrated}


def weeks(prior, recent, cal_prior=True, cal_recent=True):
    """Rows: ``prior`` values on days 27, 25, 23, ...; ``recent`` values on days 13, 11, 9, ..."""
    return ([row(27 - 2 * i, v, cal_prior) for i, v in enumerate(prior)]
            + [row(13 - 2 * i, v, cal_recent) for i, v in enumerate(recent)])


class Trend(unittest.TestCase):
    def word(self, rows, **kw):
        return body.trend(rows, TODAY, **kw)["label"]["label"]

    def test_down_flat_up_with_calibrated_rows(self):
        self.assertEqual(self.word(weeks([22, 22, 22], [21, 21, 21])), "body fat trending down (calibrated estimate)")
        self.assertEqual(self.word(weeks([22, 22, 22], [22.2, 21.9, 22.1])), "body fat trending flat (calibrated estimate)")
        self.assertEqual(self.word(weeks([20, 20, 20], [21, 21, 21])), "body fat trending up (calibrated estimate)")

    def test_the_label_is_t1_with_its_modality(self):
        t = body.trend(weeks([22, 22, 22], [21, 21, 21]), TODAY)
        self.assertEqual(t["label"], {"label": "body fat trending down (calibrated estimate)", "tier": "T1",
                                      "modality": "measured"})
        self.assertEqual((t["direction"], t["modality"]), ("down", "measured"))

    def test_one_uncalibrated_row_makes_it_a_proxy(self):
        rows = weeks([22, 22, 22], [21, 21, 21])
        rows[-1]["calibrated"] = False
        t = body.trend(rows, TODAY)
        self.assertEqual(t["label"]["label"], "body fat trending down (uncalibrated estimate)")
        self.assertEqual((t["modality"], t["label"]["modality"]), ("proxy", "proxy"))
        rows = weeks([22, 22, 22], [21, 21, 21], cal_prior=False)
        self.assertEqual(body.trend(rows, TODAY)["modality"], "proxy")

    def test_it_compares_medians_not_means(self):
        # one outlier visit moves a mean a lot and the median not at all
        self.assertEqual(self.word(weeks([22, 22, 22], [22, 22, 40])), "body fat trending flat (calibrated estimate)")
        t = body.trend(weeks([22, 23, 24, 25], [20, 21, 22]), TODAY)
        self.assertEqual((t["prior"]["median"], t["recent"]["median"], t["change"]), (23.5, 21.0, -2.5))

    def test_flat_is_a_change_under_the_threshold(self):
        self.assertEqual(body.FLAT_POINTS, 0.5)
        self.assertEqual(body.trend(weeks([22] * 3, [21.6] * 3), TODAY)["direction"], "flat")   # 0.4 under
        self.assertEqual(body.trend(weeks([22] * 3, [21.5] * 3), TODAY)["direction"], "down")   # 0.5: not under
        self.assertEqual(body.trend(weeks([22] * 3, [22.5] * 3), TODAY)["direction"], "up")
        self.assertEqual(body.trend(weeks([22] * 3, [21] * 3), TODAY, flat=1.5)["direction"], "flat")
        self.assertEqual(body.trend(weeks([22] * 3, [21.9] * 3), TODAY, flat=0.05)["direction"], "down")

    def test_fewer_than_three_rows_in_either_window_is_not_enough(self):
        for rows in (weeks([22, 22], [21, 21, 21]), weeks([22, 22, 22], [21, 21]), weeks([], []), []):
            t = body.trend(rows, TODAY)
            self.assertEqual(t["label"]["label"], "not enough measurements", rows)
            self.assertIsNone(t["direction"])
            self.assertIsNone(t["change"])
        t = body.trend(weeks([22, 22], [21, 21, 21]), TODAY)
        self.assertEqual((t["prior"]["rows"], t["recent"]["rows"]), (2, 3))

    def test_the_window_edges(self):
        rows = [row(0, 21), row(13, 21), row(6, 21), row(14, 22), row(27, 22), row(20, 22),
                row(28, 99), row(40, 99), row(-1, 1)]   # day 28 is outside both, a future day is ignored
        t = body.trend(rows, TODAY)
        self.assertEqual((t["recent"]["rows"], t["prior"]["rows"], t["direction"]), (3, 3, "down"))
        self.assertEqual(t["modality"], "measured")

    def test_rows_outside_the_windows_do_not_change_the_modality(self):
        rows = weeks([22] * 3, [21] * 3) + [row(30, 22, calibrated=False)]
        self.assertEqual(body.trend(rows, TODAY)["modality"], "measured")

    def test_no_rows_is_a_proxy_not_measured(self):
        self.assertEqual(body.trend([], TODAY)["modality"], "proxy")

    def test_malformed_rows_are_ignored_and_it_never_raises(self):
        junk = [None, 7, "x", {}, {"day": "nope", "bf_pct": 20.0, "calibrated": True},
                {"day": TODAY.isoformat(), "bf_pct": "20", "calibrated": True},
                {"day": TODAY.isoformat(), "bf_pct": 20.0, "calibrated": "yes"}]
        t = body.trend(weeks([22] * 3, [21] * 3) + junk, TODAY)
        self.assertEqual((t["recent"]["rows"], t["direction"]), (3, "down"))
        self.assertEqual(body.trend(None, TODAY)["label"]["label"], "not enough measurements")
        self.assertEqual(body.trend(junk, "not a date")["label"]["label"], "not enough measurements")
        self.assertEqual(body.trend(weeks([22] * 3, [21] * 3), TODAY, flat="x")["direction"], "down")

    def test_labels_never_carry_a_digit(self):
        rng = random.Random(7)
        for _ in range(300):
            rows = [row(rng.randrange(0, 30), rng.uniform(5, 45), rng.random() < 0.7) for _ in range(rng.randrange(12))]
            lab = body.trend(rows, TODAY, flat=rng.choice([0.1, 0.5, 2.0]))["label"]
            self.assertFalse(any(c.isdigit() for c in lab["label"]), lab)
            self.assertIn(lab["label"], body.LABELS)

    def test_review_line_is_one_digit_free_sentence(self):
        self.assertEqual(body.review_line(body.trend(weeks([22] * 3, [21] * 3), TODAY)),
                         "Body fat trending down (calibrated estimate).")
        self.assertEqual(body.review_line(body.trend([], TODAY)), "Body fat: not enough measurements.")
        self.assertEqual(body.review_line(None), "")


class FlatConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = Path(self.tmp.name) / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}

    def test_default_and_configured_threshold(self):
        self.assertEqual(body.flat_points(self.env), 0.5)
        self.cfg.write_text(json.dumps({body.FLAT_CONFIG: 1.25}))
        self.assertEqual(body.FLAT_CONFIG, "body_flat_points")
        self.assertEqual(body.flat_points(self.env), 1.25)

    def test_a_bad_threshold_falls_back_to_the_default(self):
        for v in ("1", True, -1, float("nan"), None, [1]):
            self.cfg.write_text(json.dumps({body.FLAT_CONFIG: v}) if v == v else '{"body_flat_points": NaN}')
            self.assertEqual(body.flat_points(self.env), 0.5, v)


if __name__ == "__main__":
    unittest.main()
