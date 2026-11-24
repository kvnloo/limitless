"""The memory palace offer on the pre_llm_call state card: one line of its own, through tier_audit.gate, only in a
trough, never beside the Anki offer, once per wake event (palace.json keeps the wake it was offered for). No push
and no job of its own: the card is the only place it appears.

Synthetic state only. No clock time decides anything here: the wake is the fixture's Sleep-mode event.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import shutil
import stat
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import anki, card, jobs, palace, schedule_cards  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "state"
NOW = 1894708800.0     # the fixture clock; the fixture wake is about five hours before it
H = 3600.0
TODAY = date(2030, 1, 15)
TROUGH_BANDS = {"peak": [6, 8], "trough": [1, 6]}   # moves the fixture's wake into a trough
LINE = "A short memory palace walk fits now. palace://example"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "st"
        shutil.copytree(FIX, self.st)
        self.cfg = self.dir / "config.json"
        self.config(palace_link="palace://example")
        self.audit = self.dir / "audit.jsonl"
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.cfg),
                    "LIMITLESS_AUDIT": str(self.audit)}

    def config(self, **kw):
        self.cfg.write_text(json.dumps(kw))

    def hook(self, bands=TROUGH_BANDS, clock=NOW):
        h = card.make_pre_llm_call(env=self.env, clock=lambda: clock, today=lambda: TODAY, bands=bands)
        return h(session_id="s", user_message="hi")["context"]


class OnTheCard(Base):
    def test_a_trough_adds_the_line_whole_and_digit_free(self):
        out = self.hook()
        self.assertIn(LINE, out.splitlines())
        row = json.loads(self.audit.read_text().splitlines()[-1])
        self.assertEqual((row["tier"], row["blocked"]), ("T1", False))   # the card passed tier_audit.gate
        self.assertFalse(any(c.isdigit() for c in LINE))

    def test_once_per_wake_event_and_the_mark_is_private(self):
        self.assertIn(LINE, self.hook())
        m = self.st / "palace.json"
        self.assertEqual(stat.S_IMODE(m.stat().st_mode), 0o600)
        self.assertEqual(set(json.loads(m.read_text())), {"wake_at", "offered_at"})
        self.assertNotIn("memory palace", self.hook())
        self.assertNotIn("memory palace", self.hook(clock=NOW + 0.1 * H))

    def test_never_beside_the_anki_offer(self):
        col = self.dir / "collection.anki2"
        col.write_bytes(b"")
        self.config(palace_link="palace://example", anki_collection=str(col))
        out = self.hook()
        self.assertIn(anki.OFFER, out)
        self.assertNotIn("memory palace", out)
        self.assertFalse((self.st / "palace.json").exists())

    def test_unset_is_off(self):
        self.config()
        self.assertNotIn("memory palace", self.hook())
        self.assertFalse((self.st / "palace.json").exists())

    def test_never_in_a_peak_focused_mode_or_muted(self):
        self.assertNotIn("memory palace", self.hook(bands=None))   # the fixture's default bands: a peak
        (self.st / "mode.json").write_text(json.dumps({"mode": "focused"}))
        self.assertNotIn("memory palace", self.hook())
        (self.st / "mode.json").unlink()
        (self.st / "quiet.json").write_text(json.dumps({"mode": "off", "since": "2030-01-15T11:00:00Z"}))
        self.assertNotIn("memory palace", self.hook())
        self.assertFalse((self.st / "palace.json").exists())

    def test_build_without_the_offer_has_no_line(self):
        from limitless.state_reader import StateReader
        c = card.build(StateReader(self.st), NOW, TODAY, env=self.env)
        self.assertNotIn("memory palace", c["text"])


class NoPushNoJob(unittest.TestCase):
    def test_no_job_and_no_schedule_card_names_it(self):
        for mod in ("jobs.py", "jobs_runner.py", "schedule_cards.py", "send_gate.py"):
            self.assertNotIn("palace", (ROOT / "limitless" / mod).read_text(), mod)
        self.assertTrue(jobs.EVENTS)
        self.assertFalse([c for c in schedule_cards.cards() if "palace" in json.dumps(c).lower()])

    def test_palace_sends_nothing(self):
        src = (ROOT / "limitless" / "palace.py").read_text()
        for word in ("send_gate", "brief_post", "kevin_push", "subprocess", "urlopen", "socket"):
            self.assertNotIn(word, src)


if __name__ == "__main__":
    unittest.main()
