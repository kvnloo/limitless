"""The state card says one light line while the phase is just_woke, and nothing in any other phase.
Synthetic fixtures only."""
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

from limitless import card, jobs, phase, tier_audit  # noqa: E402
from limitless.state_reader import StateReader, parse_ts  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
WAKE = parse_ts("2030-01-15T06:58:00Z")   # the fixture's last Sleep-mode off after an on
TODAY = date(2030, 1, 15)
H, M = 3600.0, 60.0
LIGHT = "Light: outdoor light now helps set the day."


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        shutil.copytree(FIX, self.st)
        self.cfg = self.root / "config.json"
        self.cfg.write_text("{}")
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_STATE": str(self.st)}

    def card(self, now):
        return card.build(StateReader(self.st), now, TODAY, env=self.env)["text"]


class CardLine(Base):
    def test_the_line_is_the_phase_modules_words(self):
        self.assertEqual(phase.CARD_LINE, LIGHT)

    def test_one_light_line_while_just_woke(self):
        text = self.card(WAKE + 20 * M)
        self.assertEqual(text.count("Light:"), 1)
        self.assertIn(LIGHT, text)
        self.assertLessEqual(len(text.splitlines()), card.MAX_LINES)

    def test_nothing_in_any_other_phase(self):
        self.assertNotIn("Light:", self.card(WAKE + 3 * H))             # day
        with open(self.st / "events.jsonl", "a") as f:
            f.write(json.dumps({"event": "wind_down", "at": "2030-01-15T20:00:00Z"}) + "\n")
        self.assertNotIn("Light:", self.card(WAKE + 14 * H))            # evening
        self.assertNotIn("Light:", self.card(WAKE - H))                 # asleep (Sleep mode on overnight)
        (self.st / "sleepmode.jsonl").write_text("")
        self.assertNotIn("Light:", self.card(WAKE + 20 * M))            # unknown: no wake event

    def test_a_fresh_posture_can_end_the_line(self):
        p = self.root / "posture.json"
        p.write_text(json.dumps({"phase": "day", "at": "2030-01-15T07:05:00Z"}))
        self.env[phase.POSTURE_ENV] = str(p)
        self.assertNotIn("Light:", self.card(WAKE + 20 * M))

    def test_light_span_follows_config(self):
        self.cfg.write_text(json.dumps({"phase_light_h": 4}))
        self.assertIn(LIGHT, self.card(WAKE + 3 * H))

    def test_own_line_under_the_window_and_peak_lines(self):
        (self.st / "asks-latest.json").unlink()
        with unittest.mock.patch.object(card, "MAX_LINES", card.MAX_LINES + 1):   # room for both lines
            lines = self.card(WAKE + 20 * M).splitlines()
        self.assertTrue(lines[1].startswith("window: "), lines)
        self.assertEqual(lines[2], "post-wake peak: open")
        self.assertEqual(lines[3], LIGHT)

    def test_a_full_card_joins_it_to_the_window_line(self):
        with unittest.mock.patch.object(card, "_saved_last_night", return_value=1):
            lines = self.card(WAKE + 20 * M).splitlines()
        self.assertEqual(len(lines), card.MAX_LINES)
        self.assertTrue(lines[1].endswith("; " + LIGHT), lines[1])
        self.assertEqual("\n".join(lines).count("Light:"), 1)

    def test_a_digit_in_the_line_drops_it(self):
        with unittest.mock.patch.object(phase, "CARD_LINE", "Light: for 2 hours."):
            self.assertNotIn("Light:", self.card(WAKE + 20 * M))

    def test_broken_input_never_breaks_the_card(self):
        with unittest.mock.patch.object(phase, "read_for", side_effect=RuntimeError("boom")):
            self.assertNotIn("Light:", self.card(WAKE + 20 * M))

    def test_card_stays_digit_free_and_passes_the_gate(self):
        text = self.card(WAKE + 20 * M)
        self.assertEqual(re.findall(r"\d", text), [])
        self.assertEqual(tier_audit.gate("pre_llm_call", text, False, env={}), text)


class Hook(Base):
    def test_pre_llm_call_sends_it_through_the_tier_audit_gate(self):
        audit = self.root / "audit.jsonl"
        env = dict(self.env, LIMITLESS_AUDIT=str(audit))
        hook = card.make_pre_llm_call(env=env, clock=lambda: WAKE + 20 * M, today=lambda: TODAY)
        out = hook()
        self.assertIn(LIGHT, out["context"])
        rows = [json.loads(ln) for ln in audit.read_text().splitlines()]
        self.assertEqual([(r["hook"], r["tier"], r["blocked"]) for r in rows], [("pre_llm_call", "T1", False)])
        self.assertNotIn("Light", audit.read_text())   # content-free: only a hash of the text

    def test_cache_drops_the_line_when_the_light_part_ends(self):
        cache, reader = card.CardCache(), StateReader(self.st)
        first = cache.get(reader, WAKE + 20 * M, TODAY, env=self.env)
        later = cache.get(reader, WAKE + H + M, TODAY, env=self.env)
        self.assertIn(LIGHT, first)
        self.assertNotIn("Light:", later)

    def test_no_new_job_push_or_reminder(self):
        self.assertFalse([n for n in jobs.SPECS if "phase" in n or "light" in n])
        src = (Path(phase.__file__)).read_text()
        for word in ("send", "push", "remind", "schedule"):
            self.assertNotIn(f"import {word}", src)
            self.assertNotIn(f"{word}(", src)


if __name__ == "__main__":
    unittest.main()
