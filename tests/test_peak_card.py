"""The state card names the post-wake peak while it applies, cued by the wake event. Synthetic fixtures only."""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card, peak, tier_audit  # noqa: E402
from limitless.state_reader import StateReader, parse_ts  # noqa: E402
from test_flow_week import make_db  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
WAKE = parse_ts("2030-01-15T06:58:00Z")   # the fixture's last Sleep-mode off after an on
TODAY = date(2030, 1, 15)
H, M = 3600.0, 60.0
LINES = ("post-wake peak: open", "post-wake peak: in use")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        shutil.copytree(FIX, self.st)
        self.cfg = self.root / "config.json"
        self.cfg.write_text("{}")
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_STATE": str(self.st)}

    def tearDown(self):
        self.tmp.cleanup()

    def card(self, now):
        return card.build(StateReader(self.st), now, TODAY, env=self.env)["text"]

    def peak_lines(self, text):
        """The peak words on the card: a line of its own, or joined to the window line when the card is full."""
        return re.findall(r"post-wake peak: (?:open|in use)", text)


class ReadFor(Base):
    def test_open_after_the_wake_event(self):
        out = peak.read_for(StateReader(self.st), WAKE + H, self.env, self.root)
        self.assertEqual((out["open"], out["label"]), (True, "post-wake peak: open"))

    def test_config_post_wake_peak_h(self):
        self.cfg.write_text(json.dumps({"post_wake_peak_h": 6}))
        self.assertTrue(peak.read_for(StateReader(self.st), WAKE + 5 * H, self.env, self.root)["open"])

    def test_no_wake_event_is_unknown(self):
        (self.st / "sleepmode.jsonl").write_text(json.dumps({"at": "2030-01-15T06:00:00Z", "on": False}) + "\n")
        out = peak.read_for(StateReader(self.st), WAKE + H, self.env, self.root)
        self.assertEqual((out["open"], out["why"]), (False, "unknown: no wake seen"))

    def test_sleep_mode_back_on_after_the_wake_is_not_open(self):
        with (self.st / "sleepmode.jsonl").open("a") as f:
            f.write(json.dumps({"at": "2030-01-15T07:30:00Z", "on": True}) + "\n")
        out = peak.read_for(StateReader(self.st), WAKE + H, self.env, self.root)
        self.assertEqual((out["open"], out["label"]), (False, None))
        self.assertTrue(out["why"].startswith("closed"))
        self.assertFalse(any(c.isdigit() for c in out["why"]))

    def test_state_dir_is_never_written(self):
        before = {f.name: f.stat().st_mtime_ns for f in self.st.iterdir()}
        peak.read_for(StateReader(self.st), WAKE + H, self.env, self.root)
        self.card(WAKE + H)
        self.assertEqual({f.name: f.stat().st_mtime_ns for f in self.st.iterdir()}, before)


class CardLine(Base):
    def test_one_open_line_inside_the_peak(self):
        text = self.card(WAKE + H)
        self.assertEqual(self.peak_lines(text), ["post-wake peak: open"])
        self.assertLessEqual(len(text.splitlines()), card.MAX_LINES)

    def test_nothing_once_the_peak_has_passed(self):
        self.assertEqual(self.peak_lines(self.card(WAKE + 3 * H)), [])

    def test_nothing_when_no_wake_is_seen(self):
        (self.st / "sleepmode.jsonl").write_text("")
        self.assertEqual(self.peak_lines(self.card(WAKE + H)), [])

    def test_card_stays_digit_free_and_passes_the_gate(self):
        text = self.card(WAKE + H)
        self.assertEqual(re.findall(r"\d", text), [])
        self.assertEqual(tier_audit.gate("pre_llm_call", text, False, env={}), text)

    def test_in_use_line_when_a_focus_block_started_inside_the_peak(self):
        db = self.root / "aw.db"
        make_db(db, spans=[(WAKE + 20 * M, WAKE + 58 * M, "editor")])
        self.cfg.write_text(json.dumps({"flow_work_apps": ["editor"]}))
        self.env["LIMITLESS_AW_DB"] = str(db)
        text = self.card(WAKE + H)
        self.assertEqual(self.peak_lines(text), ["post-wake peak: in use"])
        self.assertEqual(tier_audit.gate("pre_llm_call", text, False, env={}), text)

    def test_own_line_when_the_card_has_room(self):
        (self.st / "asks-latest.json").unlink()
        lines = self.card(WAKE + H).splitlines()
        self.assertIn("post-wake peak: open", lines)
        self.assertEqual(lines[2], "post-wake peak: open")   # right under the window line

    def test_a_full_card_joins_the_peak_to_the_window_line(self):
        with unittest.mock.patch.object(card, "_saved_last_night", return_value=1):
            lines = self.card(WAKE + H).splitlines()
        self.assertEqual(len(lines), card.MAX_LINES)
        self.assertTrue(lines[1].startswith("window: "), lines[1])
        self.assertTrue(lines[1].endswith("; post-wake peak: open"), lines[1])
        self.assertEqual(len(self.peak_lines("\n".join(lines))), 1)
        self.assertIn("asks waiting on you", "\n".join(lines))
        self.assertIn("ideas saved last night", "\n".join(lines))

    def test_cache_drops_the_line_when_the_peak_closes(self):
        cache, reader = card.CardCache(), StateReader(self.st)
        first = cache.get(reader, WAKE + H, TODAY, env=self.env)
        later = cache.get(reader, WAKE + 2 * H + M, TODAY, env=self.env)
        self.assertIn("post-wake peak: open", first)
        self.assertNotIn("post-wake peak", later)


if __name__ == "__main__":
    unittest.main()
