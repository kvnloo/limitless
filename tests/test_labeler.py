"""labeler.label: raw value -> T1 label made by code. The label never has a digit; unknown never guesses.
Synthetic values only."""
import math
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import labeler  # noqa: E402


class Shape(unittest.TestCase):
    def test_returns_label_tier_and_modality(self):
        out = labeler.label("sleep_h", 5.3, "proxy")
        self.assertEqual(out, {"label": "short", "tier": "T1", "modality": "proxy"})

    def test_unknown_modality_is_not_passed_on(self):
        self.assertIsNone(labeler.label("sleep_h", 7.6, "guess")["modality"])
        self.assertIsNone(labeler.label("sleep_h", 7.6, None)["modality"])


class Rules(unittest.TestCase):
    def lab(self, kind, v):
        return labeler.label(kind, v, "measured")["label"]

    def test_sleep_hours(self):
        self.assertEqual([self.lab("sleep_h", h) for h in (0, 5.3, 6, 7.6, 9, 9.6, 14)],
                         ["short", "short", "ok", "ok", "ok", "long", "long"])

    def test_readiness(self):
        self.assertEqual([self.lab("readiness", v) for v in (0, 27, 34, 50, 67, 71, 100)],
                         ["low", "low", "moderate", "moderate", "high", "high", "high"])

    def test_age(self):
        self.assertEqual([self.lab("age_h", a) for a in (0, 3.7, 24, 24.1, 51.3, None)],
                         ["fresh", "fresh", "fresh", "stale", "stale", "missing"])


class NeverAGuess(unittest.TestCase):
    BAD = (None, True, False, "5.3", "short", [], {}, float("nan"), float("inf"), -float("inf"), -1)

    def test_missing_or_invalid_value_is_unknown(self):
        for kind in ("sleep_h", "readiness"):
            for v in self.BAD:
                self.assertEqual(labeler.label(kind, v, "proxy")["label"], "unknown", (kind, v))

    def test_out_of_range_is_unknown(self):
        self.assertEqual(labeler.label("sleep_h", 25, "proxy")["label"], "unknown")
        self.assertEqual(labeler.label("readiness", 101, "imported")["label"], "unknown")

    def test_age_that_is_not_a_number_is_unknown_not_missing(self):
        for v in ("down", True, -0.5, float("nan")):
            self.assertEqual(labeler.label("age_h", v, "measured")["label"], "unknown", v)

    def test_unknown_kind_is_unknown(self):
        self.assertEqual(labeler.label("hrv_ms", 38.6, "measured"),
                         {"label": "unknown", "tier": "T1", "modality": "measured"})


class NoDigits(unittest.TestCase):
    def test_no_label_has_a_digit(self):
        for kind, labels in labeler.ALLOWED.items():
            for lab in labels + ("unknown",):
                self.assertEqual(re.findall(r"\d", lab), [], (kind, lab))
        vals = [-3, 0, 0.5, 5.3, 6, 7.6, 9.6, 24, 27, 51.3, 71, 99.9, 1e9, math.pi, None, "7"]
        for kind in list(labeler.ALLOWED) + ["nope"]:
            for v in vals:
                self.assertEqual(re.findall(r"\d", labeler.label(kind, v, "proxy")["label"]), [], (kind, v))

    def test_every_rule_label_is_in_its_allowed_set(self):
        for kind in labeler.ALLOWED:
            for v in (0, 1, 5, 6, 8, 9.5, 20, 30, 50, 70, 100, None):
                lab = labeler.label(kind, v, "proxy")["label"]
                self.assertIn(lab, labeler.ALLOWED[kind] + ("unknown",), (kind, v))


if __name__ == "__main__":
    unittest.main()
