"""The explain-back offer on the pre_llm_call state card: one line of its own, through tier_audit.gate, only in a
trough after work landed, once per wake event (explain-back.json keeps the wake it was offered for). No push and
no job of its own.

Synthetic state only. No clock time decides anything here: the wake is the fixture's Sleep-mode event.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import card, explain_back, jobs, schedule_cards  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "state"
NOW = 1894708800.0     # the fixture clock; the fixture wake is about five hours before it
H = 3600.0
TODAY = date(2030, 1, 15)
TROUGH_BANDS = {"peak": [6, 8], "trough": [1, 6]}   # moves the fixture's wake into a trough


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "st"
        shutil.copytree(FIX, self.st)
        self.cfg = self.dir / "config.json"
        self.cfg.write_text(json.dumps({"work_queue_dir": "lanes"}))
        self.audit = self.dir / "audit.jsonl"
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.cfg),
                    "LIMITLESS_AUDIT": str(self.audit)}

    def land(self, name="synthetic-lane", at=NOW - H):
        p = self.st / "lanes" / "done" / f"{name}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("synthetic body that is never read\n")
        os.utime(p, (at, at))

    def hook(self, env=None, bands=TROUGH_BANDS, clock=NOW):
        h = card.make_pre_llm_call(env=env or self.env, clock=lambda: clock, today=lambda: TODAY, bands=bands)
        return h(session_id="s", user_message="hi")


class OnTheCard(Base):
    def test_landed_work_in_a_trough_adds_the_line_last_and_whole(self):
        self.land()
        out = self.hook()["context"]
        self.assertEqual(out.splitlines()[-1], explain_back.OFFER)
        row = json.loads(self.audit.read_text().splitlines()[-1])
        self.assertEqual((row["tier"], row["blocked"]), ("T1", False))   # the card passed tier_audit.gate

    def test_once_per_wake_event(self):
        self.land()
        self.assertIn(explain_back.OFFER, self.hook()["context"])
        self.assertNotIn("Explain back", self.hook()["context"])
        self.land("synthetic-second", NOW - 0.5 * H)      # more work before the next wake: still offered today
        self.assertNotIn("Explain back", self.hook(clock=NOW + 0.1 * H)["context"])

    def test_the_next_wake_offers_again_only_for_work_landed_since(self):
        self.land()
        self.hook()
        nxt = 1894780680.0       # the next morning's synthetic wake: Sleep mode on, then off a night later
        with open(self.st / "sleepmode.jsonl", "a") as f:
            f.write(json.dumps({"at": "2030-01-15T22:30:00Z", "on": True}) + "\n")
            f.write(json.dumps({"at": "2030-01-16T07:58:00Z", "on": False}) + "\n")
        later, trough = nxt + 5 * H, {"cls": "trough"}   # the fixture's unlocks are stale by then: give the window
        reader = StateReader(self.st)
        self.assertEqual(explain_back.for_turn(reader, later, trough, self.env), ("", nxt))   # nothing landed since
        self.land("synthetic-overnight", nxt - 2 * H)
        self.assertEqual(explain_back.for_turn(reader, later, trough, self.env), (explain_back.OFFER, nxt))
        explain_back.mark(self.st, nxt, later)
        self.assertEqual(explain_back.for_turn(reader, later, trough, self.env), ("", nxt))

    def test_the_mark_holds_the_wake_and_no_text(self):
        self.land()
        self.hook()
        mark = json.loads((self.st / explain_back.MARK_FILE).read_text())
        self.assertEqual(sorted(mark), ["offered_at", "wake_at"])
        self.assertEqual(oct((self.st / explain_back.MARK_FILE).stat().st_mode & 0o777), "0o600")

    def test_nothing_landed_no_line(self):
        self.assertNotIn("Explain back", self.hook()["context"])
        self.land(at=NOW - 30 * H)                     # landed before the overnight window: not since
        self.assertNotIn("Explain back", self.hook()["context"])
        self.assertFalse((self.st / explain_back.MARK_FILE).exists())

    def test_no_work_queue_no_line(self):
        self.cfg.write_text("{}")
        self.land()
        self.assertNotIn("Explain back", self.hook()["context"])

    def test_not_in_the_fixture_peak(self):
        self.land()
        self.assertNotIn("Explain back", self.hook(bands=None)["context"])
        self.assertFalse((self.st / explain_back.MARK_FILE).exists())   # not offered: still to come

    def test_not_in_focused_mode_or_a_glide_block(self):
        self.land()
        (self.st / "mode.json").write_text(json.dumps({"mode": "focused"}))
        self.assertNotIn("Explain back", self.hook()["context"])
        (self.st / "mode.json").unlink()
        glide = self.dir / "attention.json"
        glide.write_text(json.dumps({"block": {"start": NOW - 600, "end": NOW + 600, "minutes": 20}}))
        self.assertNotIn("Explain back", self.hook(dict(self.env, LIMITLESS_GLIDE_ATTENTION=str(glide)))["context"])

    def test_no_wake_seen_no_line(self):
        self.land()
        (self.st / "sleepmode.jsonl").write_text("")
        out = self.hook()
        self.assertNotIn("Explain back", (out or {}).get("context", ""))

    def test_a_blocked_card_is_not_marked_as_offered(self):
        self.land()
        (self.st / "mode.json").write_text(json.dumps({"mode": "pm"}))
        orig = card.modes.LINES["pm"]
        card.modes.LINES["pm"] = "pm mode with a digit 7"
        try:
            self.assertIsNone(self.hook())
        finally:
            card.modes.LINES["pm"] = orig
        self.assertFalse((self.st / explain_back.MARK_FILE).exists())

    def test_build_adds_nothing_by_default(self):
        self.land()
        c = card.build(StateReader(self.st), NOW, TODAY, bands=TROUGH_BANDS, env=self.env)
        self.assertNotIn("Explain back", c["text"])   # limitless_state and the call brief stay as they were


class NoPushNoJob(unittest.TestCase):
    def test_no_job_and_no_schedule_card(self):
        self.assertFalse([n for n in jobs.SPECS if "explain" in n])
        self.assertFalse([c for c in schedule_cards.cards() if "explain" in json.dumps(c).lower()])


if __name__ == "__main__":
    unittest.main()
