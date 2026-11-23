"""palace mark and for_turn: at most one palace offer per wake day, kept in palace.json under the state dir
(epoch seconds only, mode 0600, like explain-back's mark); for_turn reads config, quiet and the wake event.
Synthetic state only; the wake is the fixture's Sleep-mode event, never a clock time."""
import json
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import palace  # noqa: E402
from limitless.decision_window import WindowState  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "state"
NOW = 1894708800.0     # the fixture clock; the fixture wake is a few hours before it
LINE = "A short memory palace walk fits now. palace://example"
TROUGH = WindowState("trough", since="wake")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "st"
        shutil.copytree(FIX, self.st)
        self.cfg = self.dir / "config.json"
        self.config({"palace_link": "palace://example"})
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.cfg)}
        self.reader = StateReader(self.st)

    def config(self, cfg):
        self.cfg.write_text(json.dumps(cfg))

    def turn(self, window=TROUGH, anki_line="", now=NOW):
        return palace.for_turn(self.reader, now, window, anki_line, self.env, self.dir)


class Mark(Base):
    def test_mark_is_epoch_only_and_private(self):
        self.assertTrue(palace.mark(self.st, NOW - 3600, NOW))
        p = self.st / "palace.json"
        self.assertEqual(json.loads(p.read_text()), {"wake_at": NOW - 3600, "offered_at": NOW})
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(palace.load_mark(self.st), {"wake_at": NOW - 3600, "offered_at": NOW})

    def test_a_broken_mark_reads_as_none_and_a_failed_write_is_false(self):
        self.assertIsNone(palace.load_mark(self.st))
        for body in ("not json", "[]", '{"wake_at": "x", "offered_at": 1}', '{"wake_at": true, "offered_at": 1}'):
            (self.st / "palace.json").write_text(body)
            self.assertIsNone(palace.load_mark(self.st), body)
        self.assertFalse(palace.mark(self.dir / "missing-dir", NOW, NOW))

    def test_offered_today_is_keyed_on_the_wake_event(self):
        self.assertIsNone(palace.offered_today(self.st, None))
        self.assertIs(palace.offered_today(self.st, NOW - 3600), False)
        palace.mark(self.st, NOW - 3600, NOW)
        self.assertIs(palace.offered_today(self.st, NOW - 3600), True)
        self.assertIs(palace.offered_today(self.st, NOW + 3600), False)   # the next wake: a new day


class ForTurn(Base):
    def test_a_trough_after_the_wake_offers_once(self):
        r = self.turn()
        self.assertEqual(r["line"], LINE)
        self.assertEqual(r["words"], "fits now")
        self.assertIsNotNone(r["wake"])
        palace.mark(self.st, r["wake"], NOW)
        r2 = self.turn()
        self.assertIsNone(r2["line"])
        self.assertIn("since you woke", r2["words"])

    def test_unset_is_off_and_reads_nothing_else(self):
        self.config({})
        r = self.turn()
        self.assertEqual((r["line"], r["words"], r["reason"]), (None, "off", "no memory palace link set"))

    def test_an_anki_offer_this_turn_means_no_palace_offer(self):
        r = self.turn(anki_line="trough: a short Anki review fits now")
        self.assertIsNone(r["line"])
        self.assertIn("Anki", r["words"])

    def test_muted_means_no_offer(self):
        (self.st / "quiet.json").write_text(json.dumps({"mode": "off", "since": "2030-01-15T11:00:00Z"}))
        r = self.turn()
        self.assertIsNone(r["line"])
        self.assertIn("muted", r["words"])

    def test_no_wake_seen_is_unknown_no_offer(self):
        (self.st / "sleepmode.jsonl").write_text("")
        r = self.turn()
        self.assertIsNone(r["line"])
        self.assertIsNone(r["wake"])

    def test_a_peak_or_unknown_window_never_offers(self):
        for w in (WindowState("peak"), WindowState("unknown"), None):
            self.assertIsNone(self.turn(window=w)["line"], w)

    def test_for_turn_writes_nothing(self):
        before = sorted(p.name for p in self.st.iterdir())
        self.turn()
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), before)

    def test_every_word_is_digit_free(self):
        for kw in ({}, {"anki_line": "x"}, {"window": WindowState("peak")}, {"window": None}):
            r = self.turn(**kw)
            self.assertFalse(any(c.isdigit() for c in r["words"]), r)


if __name__ == "__main__":
    unittest.main()
