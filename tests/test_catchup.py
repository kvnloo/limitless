"""catchup: after more than catchup_after_h (default 24) since the person last wrote, the first turn gets a short
catch-up: at most 5 digit-free lines, TLDR first, at most one action, unknown never shown as none.
Synthetic data only; the fixture clock is 2030-01-15T12:00:00Z."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import catchup  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_owner_messages import make_db  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
NOW = 1894708800.0
H = 3600.0
LAST = NOW - 30 * H   # the person last wrote 30 hours before this turn


def jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        shutil.copytree(FIX, self.st)
        (self.st / "README.md").unlink()
        jsonl(self.st / "jobs-sent.jsonl", [
            {"t": LAST - 5 * H, "k": "wake_brief:a", "job": "wake_brief"},     # before the absence
            {"t": LAST + 2 * H, "k": "wake_brief:b", "job": "wake_brief"},
            {"t": LAST + 9 * H, "k": "habit_checkin:b", "job": "habit_checkin"},
            {"t": LAST + 20 * H, "k": "miq:b", "job": "miq"},
        ])
        jsonl(self.st / "captures.jsonl", [
            {"at": "2030-01-13T10:00:00+00:00", "text": "synthetic older", "source": "hermes"},
            {"at": "2030-01-14T20:00:00+00:00", "text": "synthetic newer", "source": "hermes"},
        ])
        self.asks = self.root / "asks.jsonl"
        jsonl(self.asks, [{"id": "a1", "kind": "decision", "title": "synthetic", "at": LAST},
                          {"id": "a2", "kind": "fyi", "title": "synthetic", "at": LAST, "delivered_at": LAST}])
        self.db = make_db(self.root / "owner.db", [("s-tg", "user", "synthetic", LAST),
                                                  ("s-tg", "user", "synthetic", NOW - 5)])  # this turn's own
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_ASKS": str(self.asks),
                    "LIMITLESS_OWNER_DBS": str(self.db), "LIMITLESS_CONFIG": str(self.root / "none.json")}
        self.reader = StateReader(self.st)

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, last=LAST, env=None):
        return catchup.build(self.reader, NOW, last, env=self.env if env is None else env, home=self.root)


class Words(unittest.TestCase):
    def test_count_words(self):
        self.assertEqual([catchup.count_word(n) for n in (None, 0, 1, 2, 4, 5, 40)],
                         ["unknown", "none", "one", "a few", "a few", "many", "many"])

    def test_away_words_are_digit_free(self):
        for h in (13, 30, 80, 200, 2000):
            self.assertFalse(any(c.isdigit() for c in catchup.away_word(h)), h)


class Build(Base):
    def test_at_most_five_digit_free_lines_tldr_first(self):
        c = self.build()
        self.assertLessEqual(len(c["lines"]), catchup.MAX_LINES)
        self.assertEqual(catchup.MAX_LINES, 5)
        self.assertEqual(c["text"], "\n".join(c["lines"]))
        self.assertTrue(c["lines"][0].startswith("[limitless] catch-up"), c["lines"])
        self.assertFalse(any(ch.isdigit() for ch in c["text"]), c["text"])

    def test_the_lines(self):
        text = self.build()["text"]
        self.assertIn("not recording: anki, bike, scale", text)
        self.assertIn("habit week: running, today Done", text)
        self.assertIn("messages sent: a few", text)          # three delivered after LAST, one before
        self.assertIn("captures saved: one", text)           # only the capture after LAST
        self.assertIn("asks waiting: one", text)             # the delivered FYI is not waiting

    def test_at_most_one_action(self):
        c = self.build()
        self.assertEqual(c["text"].count("next:"), 1)
        self.assertIn("next: look at the asks waiting", c["lines"][0])

    def test_no_action_when_nothing_needs_the_person(self):
        jsonl(self.asks, [])
        (self.st / "inputs.json").write_text(json.dumps({"at": "2030-01-15T11:30:00Z",
                                                          "ageHours": {"phone": 0.2}}))
        c = self.build()
        self.assertNotIn("next:", c["text"])
        self.assertIn("nothing needs you", c["lines"][0])
        self.assertIn("inputs: all recording", c["text"])
        self.assertIn("asks waiting: none", c["text"])

    def test_a_digit_in_an_input_name_is_masked(self):
        (self.st / "inputs.json").write_text(json.dumps({"at": "2030-01-15T11:30:00Z",
                                                          "ageHours": {"ring2": "down"}}))
        text = self.build()["text"]
        self.assertFalse(any(ch.isdigit() for ch in text), text)
        self.assertIn("ring#", text)

    def test_a_present_but_empty_source_is_none(self):
        jsonl(self.st / "jobs-sent.jsonl", [{"t": LAST - H, "k": "x", "job": "wake_brief"}])
        (self.st / "captures.jsonl").write_text("")
        text = self.build()["text"]
        self.assertIn("messages sent: none", text)
        self.assertIn("captures saved: none", text)


class Unknown(Base):
    def test_missing_sources_are_unknown_never_none(self):
        empty = self.root / "empty"
        empty.mkdir()
        self.reader = StateReader(empty)
        c = self.build(env={"LIMITLESS_STATE": str(empty), "LIMITLESS_CONFIG": str(self.root / "none.json")})
        text = c["text"]
        for want in ("inputs: unknown", "habit week: unknown", "messages sent: unknown",
                     "captures saved: unknown", "asks waiting: unknown"):
            self.assertIn(want, text)
        self.assertNotIn("none", text)
        self.assertLessEqual(len(c["lines"]), 5)

    def test_a_configured_but_missing_asks_queue_is_unknown(self):
        self.asks.unlink()
        self.assertIn("asks waiting: unknown", self.build()["text"])

    def test_no_habit_week_is_none_started_when_habit_json_exists(self):
        (self.st / "habit.json").write_text(json.dumps({"week_of": "2029-12-01", "habit": "synthetic"}))
        self.assertIn("habit week: over", self.build()["text"])
        (self.st / "habit.json").write_text(json.dumps({}))
        self.assertIn("habit week: none started", self.build()["text"])


class Gap(Base):
    def test_after_h_default_and_config(self):
        self.assertEqual(catchup.after_h(self.env, self.root), 24.0)
        cfg = self.root / "cfg.json"
        cfg.write_text(json.dumps({"catchup_after_h": 48}))
        self.assertEqual(catchup.after_h({"LIMITLESS_CONFIG": str(cfg)}, self.root), 48.0)
        for bad in (0, -3, "x", True, None):
            cfg.write_text(json.dumps({"catchup_after_h": bad}))
            self.assertEqual(catchup.after_h({"LIMITLESS_CONFIG": str(cfg)}, self.root), 24.0, bad)

    def test_last_seen_is_the_message_before_this_turn(self):
        self.assertEqual(catchup.last_seen(self.reader, NOW, self.env, self.root), LAST)

    def test_last_seen_unknown_without_owner_dbs(self):
        env = dict(self.env)
        del env["LIMITLESS_OWNER_DBS"]
        self.assertIsNone(catchup.last_seen(self.reader, NOW, env, self.root))


class Hook(Base):
    def hook(self, **kw):
        return catchup.make_pre_llm_call(env=self.env, clock=lambda: self.now, home=self.root, **kw)

    def call(self, hook):
        return hook(session_id="s", user_message="hi", conversation_history=[], is_first_turn=False,
                    model="m", platform="cli")

    def test_injects_once_after_the_gap(self):
        self.now = NOW
        hook = self.hook()
        out = self.call(hook)
        self.assertTrue(out["context"].startswith("[limitless] catch-up"), out)
        self.assertFalse(any(ch.isdigit() for ch in out["context"]))
        self.assertIsNone(self.call(hook))            # second turn, same last-seen: no repeat
        self.now = NOW + 60
        self.assertIsNone(self.call(hook))

    def test_nothing_inside_the_gap(self):
        self.now = NOW
        self.env["LIMITLESS_OWNER_DBS"] = str(make_db(self.root / "recent.db", [("s-tg", "user", "x", NOW - 3 * H)]))
        self.assertIsNone(self.call(self.hook()))

    def test_config_after_h(self):
        self.now = NOW
        cfg = self.root / "cfg.json"
        cfg.write_text(json.dumps({"catchup_after_h": 48}))
        self.env["LIMITLESS_CONFIG"] = str(cfg)
        self.assertIsNone(self.call(self.hook()))

    def test_nothing_without_owner_dbs_or_state(self):
        self.now = NOW
        del self.env["LIMITLESS_OWNER_DBS"]
        self.assertIsNone(self.call(self.hook()))
        self.env["LIMITLESS_OWNER_DBS"] = str(self.db)
        self.env["LIMITLESS_STATE"] = str(self.root / "nope")
        self.assertIsNone(self.call(self.hook()))

    def test_a_new_absence_injects_again(self):
        self.now = NOW
        hook = self.hook()
        self.assertIsNotNone(self.call(hook))
        later = NOW + 50 * H
        make_db(self.root / "later.db", [("s-tg", "user", "x", NOW), ("s-tg", "user", "x", later - 5)])
        self.env["LIMITLESS_OWNER_DBS"] = str(self.root / "later.db")
        self.now = later
        self.assertIsNotNone(self.call(hook))

    def test_goes_through_the_gate(self):
        self.now = NOW
        audit = self.root / "audit.jsonl"
        self.env["LIMITLESS_AUDIT"] = str(audit)
        self.call(self.hook())
        rows = [json.loads(ln) for ln in audit.read_text().splitlines()]
        self.assertEqual([(r["hook"], r["tier"], r["blocked"]) for r in rows], [("catchup", "T1", False)])

    def test_a_digit_is_dropped_by_the_gate(self):
        self.now = NOW
        with mock.patch.object(catchup, "build", return_value={"text": "leak 42", "lines": ["leak 42"]}):
            self.assertIsNone(self.call(self.hook()))

    def test_writes_and_sends_nothing(self):
        self.now = NOW
        before = sorted((p.name, p.stat().st_mtime_ns) for p in self.st.iterdir())
        self.call(self.hook())
        self.assertEqual(sorted((p.name, p.stat().st_mtime_ns) for p in self.st.iterdir()), before)

    def test_never_raises(self):
        self.now = NOW
        with mock.patch.object(catchup, "build", side_effect=RuntimeError("boom")):
            self.assertIsNone(self.call(self.hook()))


class Tool(Base):
    def test_envelope(self):
        out = catchup.tool(self.reader, NOW, env=self.env, home=self.root)
        self.assertTrue({"value", "modality", "age_h", "evidence_tier", "label"} <= set(out), out)
        self.assertEqual(out["modality"], "messages")
        self.assertEqual(out["age_h"], 30.0)
        self.assertEqual(out["label"]["tier"], "T1")
        self.assertEqual(out["label"]["label"], "away")
        self.assertEqual(out["value"]["lines"], self.build()["lines"])

    def test_not_away(self):
        self.env["LIMITLESS_OWNER_DBS"] = str(make_db(self.root / "recent.db", [("s-tg", "user", "x", NOW - 3 * H)]))
        out = catchup.tool(self.reader, NOW, env=self.env, home=self.root)
        self.assertEqual(out["label"]["label"], "not away")
        self.assertTrue(out["value"]["lines"])

    def test_missing_without_owner_dbs(self):
        del self.env["LIMITLESS_OWNER_DBS"]
        out = catchup.tool(self.reader, NOW, env=self.env, home=self.root)
        self.assertIsNone(out["value"])
        self.assertTrue(out["reason"])


if __name__ == "__main__":
    unittest.main()
