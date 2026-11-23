"""limitless_propose: the state dict built read-only from the existing tools' labels, one derived envelope.
Synthetic fixtures only."""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import plugin, propose as p, quiet, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state"
NOW = 1894708800.0
TODAY = date.fromtimestamp(NOW)
FIELDS = {"value", "modality", "age_h", "evidence_tier"}


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshot(d: Path) -> dict:
    return {str(f.relative_to(d)): (f.stat().st_mtime_ns, f.stat().st_size) for f in d.rglob("*") if f.is_file()}


class Tool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name) / "st"
        shutil.copytree(FIX, self.st)
        self.cfg_path = Path(self.tmp.name) / "config.json"
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.cfg_path)}

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, **kw):
        self.cfg_path.write_text(json.dumps(kw))

    def woke(self, hours_ago):
        """Sleep mode on through the night, off ``hours_ago`` before NOW; a fresh poll and a recent unlock."""
        wake = NOW - hours_ago * 3600
        rows = [{"at": iso(wake - 8 * 3600), "on": True}, {"at": iso(wake), "on": False}]
        (self.st / "sleepmode.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": iso(NOW - 60), "ok": True}))
        (self.st / "unlocks.jsonl").write_text(json.dumps({"at": iso(NOW - 120)}) + "\n")

    def habit_today(self, answer=None):
        h = json.loads((self.st / "habit.json").read_text())
        h["checkins"].pop(TODAY.isoformat(), None)
        if answer:
            h["checkins"][TODAY.isoformat()] = answer
        (self.st / "habit.json").write_text(json.dumps(h))

    def state(self):
        return tools.propose_state(StateReader(self.st), NOW, TODAY, env=self.env)[0]

    def call(self):
        with mock.patch.dict(os.environ, self.env), mock.patch("time.time", return_value=NOW):
            return json.loads(plugin._handler(plugin.TOOLS["limitless_propose"][1], "limitless_propose")({}))

    def test_state_has_every_label_and_only_known_or_unknown_values(self):
        st = self.state()
        self.assertEqual(set(st), set(p.STATE_KEYS))
        for k, v in st.items():
            self.assertTrue(v is None or v in p.STATE_KEYS[k], (k, v))

    def test_fixture_labels(self):
        st = self.state()
        self.assertEqual((st["asleep"], st["window"], st["quiet"], st["mode"], st["anki"], st["palace"]),
                         (False, "peak", "on", "none", "not set", "not set"))
        self.assertEqual((st["habit_week"], st["habit_today"]), ("running", "Done"))
        self.assertIsNone(st["peak_ask"])        # no asks queue configured: unknown, not none
        self.assertIsNone(st["focus_block"])     # no activity DB: unknown

    def test_envelope_is_derived_with_a_tier_and_a_label(self):
        res = self.call()
        self.assertTrue(FIELDS <= set(res), res)
        self.assertEqual(res["modality"], "derived")
        self.assertIn(res["evidence_tier"], ("direct", "indirect", "stale", "none"))
        v = res["value"]
        self.assertTrue({"action", "because", "rule_id", "evidence", "note"} <= set(v))
        self.assertEqual(v["action"], p.NO_SUGGESTION)   # today is answered and nothing else fits
        self.assertEqual(res["label"], {"label": "no suggestion", "tier": "T1", "modality": "derived"})
        self.assertEqual(re.findall(r"\d", json.dumps(v)), [])
        self.assertEqual(re.findall(r"\d", res["label"]["label"]), [])

    def test_habit_unanswered_suggests_the_checkin(self):
        self.habit_today()
        res = self.call()
        self.assertEqual((res["value"]["action"], res["value"]["rule_id"]),
                         ("answer today's habit check-in", "habit-checkin"))
        self.assertEqual(res["label"]["label"], "answer today's habit check-in")
        self.assertEqual(res["value"]["evidence"], ["habit_week", "habit_today"])

    def test_quiet_off_or_focused_mode_holds(self):
        self.habit_today()
        quiet.write(self.st, quiet.OFF, NOW - 60)
        self.assertEqual(self.call()["value"]["rule_id"], "quiet")
        (self.st / "quiet.json").unlink()
        (self.st / "mode.json").write_text(json.dumps({"mode": "focused"}))
        self.assertEqual(self.call()["value"]["rule_id"], "focused-mode")

    def test_peak_open_with_a_waiting_decision(self):
        self.woke(1)
        q = Path(self.tmp.name) / "asks.jsonl"
        q.write_text(json.dumps({"id": "a", "kind": "decision", "title": "Pick a synthetic option",
                                 "at": iso(NOW - 600)}) + "\n")
        self.env["LIMITLESS_ASKS"] = str(q)
        st = self.state()
        self.assertEqual((st["post_wake_peak"], st["peak_ask"]), ("open", "waiting"))
        self.assertEqual(self.call()["value"]["rule_id"], "peak-ask")
        # one decision per peak window: once one was delivered since the wake, none is suggested
        q.write_text(q.read_text() + json.dumps({"id": "b", "kind": "decision", "title": "Done one",
                                                 "at": iso(NOW - 900), "delivered_at": NOW - 300}) + "\n")
        self.assertEqual(self.state()["peak_ask"], "spent")

    def test_trough_with_anki_set(self):
        self.woke(7)
        self.config(anki_collection=str(Path(self.tmp.name) / "collection.anki2"))
        st = self.state()
        self.assertEqual((st["window"], st["anki"]), ("trough", "set"))
        self.assertEqual(self.call()["value"]["rule_id"], "anki-trough")

    def test_trough_with_a_palace_link_and_no_anki(self):
        self.woke(7)
        self.config(palace_link="palace://example")
        st = self.state()
        self.assertEqual((st["window"], st["anki"], st["palace"]), ("trough", "not set", "set"))
        res = self.call()
        self.assertEqual((res["value"]["rule_id"], res["value"]["action"]), ("palace-trough", "a short memory palace walk"))
        self.assertEqual(res["label"]["label"], "a short memory palace walk")
        self.config(palace_link="palace://example", anki_collection=str(Path(self.tmp.name) / "collection.anki2"))
        self.assertEqual(self.call()["value"]["rule_id"], "anki-trough")   # one learning offer per trough
        self.config(palace_link="palace://room-seven-has-a-digit-7")
        self.assertEqual(self.state()["palace"], "not set")   # a link that cannot ride in a line is off

    def test_asleep(self):
        rows = [{"at": iso(NOW - 3600), "on": True}]
        (self.st / "sleepmode.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": iso(NOW - 60), "ok": True}))
        self.habit_today()
        st = self.state()
        self.assertIs(st["asleep"], True)
        self.assertEqual(self.call()["value"]["rule_id"], "asleep")

    def test_read_only(self):
        self.habit_today()
        self.config(anki_collection=str(Path(self.tmp.name) / "collection.anki2"))
        before = snapshot(Path(self.tmp.name))
        self.call()
        self.assertEqual(snapshot(Path(self.tmp.name)), before)

    def test_missing_state_dir_is_no_suggestion(self):
        self.env["LIMITLESS_STATE"] = str(Path(self.tmp.name) / "nowhere")
        res = self.call()
        self.assertEqual(res["value"]["action"], p.NO_SUGGESTION)
        self.assertEqual(res["evidence_tier"], "none")


class Wiring(unittest.TestCase):
    def test_description_says_it_only_suggests(self):
        desc = plugin.TOOLS["limitless_propose"][0]["description"]
        for words in ("only suggests", "ask the person", "NO_SUGGESTION", "derived"):
            self.assertIn(words, desc)

    def test_in_the_manifest(self):
        self.assertIn("  - limitless_propose\n", (ROOT / "plugin.yaml").read_text())

    def test_not_on_the_pre_llm_call_card(self):
        for mod in ("card.py", "catchup.py"):
            self.assertNotIn("propose", (ROOT / "limitless" / mod).read_text(), mod)


class Derived(unittest.TestCase):
    def test_tier_is_the_weakest_evidence_used(self):
        r = {"action": "a short Anki review", "because": "x", "rule_id": "anki-trough", "evidence": ["window", "anki"]}
        tiers = {"window": "indirect", "anki": "direct", "quiet": "stale"}
        self.assertEqual(p.derived(r, tiers)["evidence_tier"], "indirect")

    def test_default_takes_the_weakest_known_input(self):
        r = p.propose({})
        self.assertEqual(p.derived(r, {"quiet": "stale", "mode": "direct", "anki": "none"})["evidence_tier"], "stale")
        self.assertEqual(p.derived(r, {"anki": "none"})["evidence_tier"], "none")
        self.assertEqual(p.derived(r, {})["evidence_tier"], "none")

    def test_shape(self):
        env = p.derived(p.propose({}), {})
        self.assertEqual((env["modality"], env["age_h"]), ("derived", None))
        self.assertNotIn("must", env["value"]["note"])
        self.assertIn("ask", env["value"]["note"])


if __name__ == "__main__":
    unittest.main()
