"""Every tool result is {value, modality, age_h, evidence_tier}; missing data is value null + reason."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import envelope as e  # noqa: E402


class Envelope(unittest.TestCase):
    def test_has_exactly_the_four_fields(self):
        env = e.envelope(5.5, "proxy", 3.24)
        self.assertEqual(set(env), {"value", "modality", "age_h", "evidence_tier"})
        self.assertEqual(env["value"], 5.5)
        self.assertEqual(env["modality"], "proxy")
        self.assertEqual(env["age_h"], 3.2)  # one decimal

    def test_modality_is_one_of_five(self):
        self.assertEqual(e.MODALITIES, ("measured", "imported", "proxy", "self_report", "messages"))
        for m in e.MODALITIES:
            self.assertEqual(e.envelope(1, m, 0)["modality"], m)
        with self.assertRaises(ValueError):
            e.envelope(1, "guess", 0)

    def test_tier_follows_modality_and_age(self):
        self.assertEqual(e.envelope(1, "measured", 2)["evidence_tier"], "direct")
        self.assertEqual(e.envelope(1, "imported", 2)["evidence_tier"], "direct")
        self.assertEqual(e.envelope(1, "self_report", 2)["evidence_tier"], "direct")
        self.assertEqual(e.envelope(1, "proxy", 2)["evidence_tier"], "indirect")
        self.assertEqual(e.envelope(1, "measured", 24.5)["evidence_tier"], "stale")
        self.assertEqual(e.envelope(1, "measured", None)["evidence_tier"], "stale")  # age unknown

    def test_missing_is_null_with_a_reason_never_a_guess(self):
        env = e.missing("no digest in the state dir")
        self.assertIsNone(env["value"])
        self.assertEqual(env["reason"], "no digest in the state dir")
        self.assertEqual(env["evidence_tier"], "none")
        self.assertIsNone(env["modality"])
        self.assertIsNone(env["age_h"])

    def test_null_value_needs_a_reason(self):
        with self.assertRaises(ValueError):
            e.envelope(None, "measured", 1)
        env = e.envelope(None, "measured", 1, reason="sensor off")
        self.assertEqual((env["value"], env["evidence_tier"], env["reason"]), (None, "none", "sensor off"))

    def test_missing_reason_must_be_words(self):
        with self.assertRaises(ValueError):
            e.missing("")

    def test_negative_age_is_rejected(self):
        with self.assertRaises(ValueError):
            e.envelope(1, "measured", -1)


if __name__ == "__main__":
    unittest.main()
