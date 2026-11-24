"""limitless_palace: read-only. Whether the one memory palace offer fits now, in words only: "off", "fits now" or
"not now: <reason in words>"; modality derived, a digit-free T1 label. Synthetic state and links only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import palace, plugin, tools  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "state"
NOW = 1894708800.0
TROUGH_BANDS = {"peak": [6, 8], "trough": [1, 6]}   # moves the fixture's wake into a trough
FIELDS = {"value", "modality", "age_h", "evidence_tier"}
LINE = "A short memory palace walk fits now. palace://example"


def snapshot(d: Path) -> dict:
    return {str(p.relative_to(d)): (p.stat().st_mtime_ns, p.read_bytes()) for p in sorted(d.rglob("*")) if p.is_file()}


class Envelope(unittest.TestCase):
    def test_off(self):
        out = tools.palace({"line": None, "wake": None, "word": "off", "reason": palace.NO_LINK, "words": "off"})
        self.assertEqual(out["value"], {"label": "off", "why": "no memory palace link set"})
        self.assertEqual((out["modality"], out["age_h"], out["evidence_tier"]), ("derived", None, "direct"))
        self.assertEqual(out["label"], {"label": "off", "tier": "T1", "modality": "derived"})

    def test_fits_now_carries_the_line(self):
        out = tools.palace({"line": LINE, "wake": NOW - 3600, "word": "fits now", "reason": None, "words": "fits now"})
        self.assertEqual(out["value"], {"label": "fits now", "line": LINE})
        self.assertEqual(out["label"]["label"], "fits now")
        self.assertNotIn("wake", json.dumps(out))   # no time leaves the tool

    def test_not_now_says_why_in_words(self):
        w = f"not now: {palace.MUTED}"
        out = tools.palace({"line": None, "wake": NOW, "word": "not now", "reason": palace.MUTED, "words": w})
        self.assertEqual(out["value"], {"label": w})
        self.assertEqual(out["evidence_tier"], "indirect")

    def test_a_broken_result_is_not_now(self):
        for r in (None, {}, {"words": "fits now 7"}, {"word": "fits now", "words": "fits now", "line": "x 7"}):
            out = tools.palace(r)
            self.assertTrue(out["value"]["label"].startswith("not now: "), r)
            self.assertEqual(re.findall(r"\d", json.dumps(out["value"])), [], r)


class ThroughThePlugin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "st"
        shutil.copytree(FIX, self.st)
        self.cfg = self.dir / "config.json"
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.cfg)}

    def config(self, **kw):
        self.cfg.write_text(json.dumps(kw))

    def call(self):
        with mock.patch.dict(os.environ, self.env), mock.patch("time.time", return_value=NOW):
            return json.loads(plugin._handler(plugin.TOOLS["limitless_palace"][1], "limitless_palace")({}))

    def test_unset_is_off(self):
        self.config(window_bands=TROUGH_BANDS)
        out = self.call()
        self.assertTrue(FIELDS <= set(out), out)
        self.assertEqual(out["value"], {"label": "off", "why": "no memory palace link set"})

    def test_a_trough_fits_now(self):
        self.config(window_bands=TROUGH_BANDS, palace_link="palace://example")
        out = self.call()
        self.assertEqual(out["value"], {"label": "fits now", "line": LINE})
        self.assertEqual(out["modality"], "derived")

    def test_a_peak_is_not_now_with_the_reason(self):
        self.config(palace_link="palace://example")   # the fixture's default bands: a peak
        out = self.call()
        self.assertEqual(out["value"]["label"], "not now: your focus is high right now, so this waits for a lighter moment")

    def test_an_anki_offer_is_not_now(self):
        col = self.dir / "collection.anki2"
        col.write_bytes(b"")
        self.config(window_bands=TROUGH_BANDS, palace_link="palace://example", anki_collection=str(col))
        self.assertIn("Anki", self.call()["value"]["label"])

    def test_read_only_the_tool_never_marks(self):
        self.config(window_bands=TROUGH_BANDS, palace_link="palace://example")
        before = snapshot(self.dir)
        self.call()
        self.call()
        self.assertEqual(snapshot(self.dir), before)
        self.assertEqual(self.call()["value"]["label"], "fits now")   # only the card's hook marks

    def test_words_only_no_digit(self):
        for kw in ({}, {"palace_link": "palace://example"}, {"palace_link": "palace://example", "window_bands": TROUGH_BANDS}):
            self.config(**kw)
            out = self.call()
            self.assertEqual(re.findall(r"\d", json.dumps(out["value"]) + out["label"]["label"]), [], kw)

    def test_registered_and_in_the_manifest(self):
        self.assertIn("limitless_palace", plugin.TOOLS)
        self.assertIn("  - limitless_palace", (ROOT / "plugin.yaml").read_text().splitlines())
        desc = plugin.TOOLS["limitless_palace"][0]["description"]
        for words in ("trough", "Read-only", "palace_link", "fits now", "not now"):
            self.assertIn(words, desc)


if __name__ == "__main__":
    unittest.main()
