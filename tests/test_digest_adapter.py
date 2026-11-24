"""The live sync writes digests as {builtAt, phoneProxy: {gapHours, ...}, noop: {...}}, not {at, metrics}.
The reader must turn that shape into {at, metrics} so the card can label it. Synthetic values only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card  # noqa: E402
from limitless.state_reader import StateReader, normalize_digest  # noqa: E402

NOW = 1894708800.0  # 2030-01-15T12:00:00Z

SYNC_ROW = {
    "builtAt": "2030-01-15T07:10:00Z",
    "wakeDay": "2030-01-15",
    "phoneProxy": {"basis": "unlock gap", "gapHours": 5.4, "onset": "x", "wake": "y"},
    "noop": {"available": False, "hrAgeHours": 99.0, "journal": []},
}


class NormalizeDigest(unittest.TestCase):
    def test_sync_row_gets_at_from_built_at(self):
        self.assertEqual(normalize_digest(SYNC_ROW)["at"], "2030-01-15T07:10:00Z")

    def test_sync_row_sleep_comes_from_the_phone_proxy(self):
        m = normalize_digest(SYNC_ROW)["metrics"]
        self.assertEqual(m["sleep_h"], {"value": 5.4, "modality": "proxy"})

    def test_no_readiness_is_invented(self):
        self.assertNotIn("readiness", normalize_digest(SYNC_ROW)["metrics"])

    def test_a_row_already_in_metrics_shape_is_unchanged(self):
        row = {"at": "2030-01-15T07:00:00Z", "metrics": {"sleep_h": {"value": 7.0, "modality": "measured"}}}
        self.assertEqual(normalize_digest(row), row)

    def test_missing_gap_hours_gives_no_sleep_metric(self):
        row = dict(SYNC_ROW, phoneProxy={"basis": "unlock gap"})
        self.assertNotIn("sleep_h", normalize_digest(row)["metrics"])


class CardReadsSyncShape(unittest.TestCase):
    def test_card_labels_sleep_from_a_sync_digest_without_digits(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "digests.jsonl").write_text(json.dumps(SYNC_ROW) + "\n")
            c = card.build(StateReader(Path(d)), NOW, date(2030, 1, 15))
        self.assertIn("sleep short (proxy)", c["text"])
        self.assertIn("readiness unknown", c["text"])
        self.assertFalse(any(ch.isdigit() for ch in c["text"]))


if __name__ == "__main__":
    unittest.main()
