"""limitless_phase: the phase in digit-free words, an evidence envelope, read-only. Synthetic fixtures only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import phase as ph, plugin, tools  # noqa: E402
from limitless.state_reader import StateReader, parse_ts  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
WAKE = parse_ts("2030-01-15T06:58:00Z")   # the fixture's last Sleep mode off after on
NOW = 1894708800.0                       # the fixture clock: five hours after the wake event
H = 3600.0
ENVELOPE = {"value", "modality", "age_h", "evidence_tier"}


class PhaseTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        shutil.copytree(FIX, self.st)
        self.cfg = self.dir / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_STATE": str(self.st)}

    def config(self, **kw):
        self.cfg.write_text(json.dumps(kw))

    def poll(self, at):
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": at, "ok": True}))

    def call(self, now):
        return tools.phase(StateReader(self.st), now, env=self.env, home=self.dir)

    def posture(self, obj):
        p = self.dir / "posture.json"
        p.write_text(obj if isinstance(obj, str) else json.dumps(obj))
        return p

    def test_just_woke_is_a_proxy_from_the_wake_event(self):
        res = self.call(WAKE + 0.5 * H)
        self.assertTrue(ENVELOPE <= set(res))
        self.assertEqual(res["value"], {"phase": "just_woke"})
        self.assertEqual((res["modality"], res["evidence_tier"], res["age_h"]), ("proxy", "indirect", 0.5))
        self.assertEqual(res["label"], {"label": "just woke: a good time for outdoor light", "tier": "T1",
                                        "modality": "proxy"})

    def test_day_after_the_light_span(self):
        res = self.call(NOW)
        self.assertEqual(res["value"], {"phase": "day"})
        self.assertEqual(res["label"]["label"], "day: the main part of the day")

    def test_light_span_from_config(self):
        self.config(phase_light_h=6)
        self.assertEqual(self.call(NOW)["value"], {"phase": "just_woke"})

    def test_evening_after_a_wind_down_event(self):
        with open(self.st / "events.jsonl", "a") as f:
            f.write(json.dumps({"event": "wind_down", "at": "2030-01-15T11:00:00Z"}) + "\n")
        res = self.call(NOW)
        self.assertEqual(res["value"], {"phase": "evening"})
        self.assertEqual(res["label"]["label"], "evening: wind-down part of the day")

    def test_asleep_while_sleep_mode_is_on(self):
        with open(self.st / "sleepmode.jsonl", "a") as f:
            f.write(json.dumps({"at": "2030-01-15T11:30:00Z", "on": True}) + "\n")
        self.poll("2030-01-15T11:59:00Z")
        res = self.call(NOW)
        self.assertEqual(res["value"], {"phase": "asleep"})
        self.assertEqual(res["label"]["label"], "asleep: Sleep mode is on")

    def test_unknown_without_a_wake_event(self):
        (self.st / "sleepmode.jsonl").write_text("")
        res = self.call(NOW)
        self.assertEqual(res["value"], {"phase": "unknown"})
        self.assertEqual((res["evidence_tier"], res["age_h"]), ("none", None))
        self.assertEqual(res["label"]["label"], "unknown: no wake event yet")
        self.assertEqual(res["reason"], "no wake event yet")

    def test_fresh_posture_overrides_and_is_derived(self):
        p = self.posture({"phase": "evening", "at": "2030-01-15T10:00:00Z", "extra": {"x": 1}})
        self.env[ph.POSTURE_ENV] = str(p)
        res = self.call(NOW)
        self.assertEqual(res["value"], {"phase": "evening"})
        self.assertEqual((res["modality"], res["age_h"], res["evidence_tier"]), ("derived", 2.0, "indirect"))

    def test_posture_from_config_key(self):
        p = self.posture({"phase": "day", "at": "2030-01-15T07:10:00Z"})
        self.config(posture_file=str(p))
        res = self.call(WAKE + 0.5 * H)
        self.assertEqual((res["value"], res["modality"]), ({"phase": "day"}, "derived"))

    def test_env_beats_config_for_the_posture_path(self):
        self.config(posture_file=str(self.posture({"phase": "day", "at": "2030-01-15T07:10:00Z"})))
        other = self.dir / "other.json"
        other.write_text(json.dumps({"phase": "evening", "at": "2030-01-15T07:10:00Z"}))
        self.env[ph.POSTURE_ENV] = str(other)
        self.assertEqual(self.call(WAKE + 0.5 * H)["value"], {"phase": "evening"})

    def test_unknown_posture_name_is_ignored_with_a_reason(self):
        self.env[ph.POSTURE_ENV] = str(self.posture({"phase": "subjective_dusk", "at": "2030-01-15T11:00:00Z"}))
        res = self.call(NOW)
        self.assertEqual((res["value"], res["modality"]), ({"phase": "day"}, "proxy"))
        self.assertIn("not a known phase", res["posture_ignored"])

    def test_stale_posture_is_ignored(self):
        self.env[ph.POSTURE_ENV] = str(self.posture({"phase": "evening", "at": "2030-01-14T20:00:00Z"}))
        res = self.call(NOW)
        self.assertEqual(res["value"], {"phase": "day"})
        self.assertIn("older than the wake event", res["posture_ignored"])

    def test_missing_or_broken_posture_file_is_ignored(self):
        for text in (None, "{not json", "[]", "null"):
            p = self.dir / "posture.json"
            if text is None:
                if p.exists():
                    p.unlink()
            else:
                p.write_text(text)
            self.env[ph.POSTURE_ENV] = str(p)
            res = self.call(NOW)
            self.assertEqual(res["value"], {"phase": "day"}, text)
            self.assertTrue(res["posture_ignored"], text)

    def test_posture_without_a_time_uses_the_file_time(self):
        p = self.posture({"phase": "evening"})
        os.utime(p, (NOW - H, NOW - H))
        self.env[ph.POSTURE_ENV] = str(p)
        self.assertEqual(self.call(NOW)["value"], {"phase": "evening"})

    def test_last_object_of_a_list_is_read(self):
        self.env[ph.POSTURE_ENV] = str(self.posture([{"phase": "day", "at": "2030-01-15T08:00:00Z"},
                                                     {"phase": "evening", "at": "2030-01-15T11:00:00Z"}]))
        self.assertEqual(self.call(NOW)["value"], {"phase": "evening"})

    def test_words_are_digit_free_with_no_raw_time(self):
        for now in (WAKE - H, WAKE + 0.2 * H, NOW, WAKE + 30 * H):
            res = self.call(now)
            text = json.dumps([res["value"], res["label"]["label"], res["why"], res.get("reason"),
                               res.get("posture_ignored")])
            self.assertFalse(any(c.isdigit() for c in text), res)

    def test_nothing_is_written(self):
        before = sorted((p.name, p.stat().st_mtime_ns) for p in self.st.iterdir())
        self.call(NOW)
        self.assertEqual(sorted((p.name, p.stat().st_mtime_ns) for p in self.st.iterdir()), before)

    def test_registered_tool_through_the_handler(self):
        self.assertIn("limitless_phase", plugin.TOOLS)
        desc = plugin.TOOLS["limitless_phase"][0]["description"]
        self.assertIn("never a clock time", desc)
        self.assertFalse(any(c.isdigit() for c in desc.split("Returns an evidence envelope")[0]))
        with mock.patch.dict(os.environ, self.env, clear=False), mock.patch("time.time", return_value=WAKE + 0.5 * H):
            res = json.loads(plugin._handler(plugin.TOOLS["limitless_phase"][1], "limitless_phase")({}))
        self.assertEqual(res["value"], {"phase": "just_woke"})
        self.assertEqual(res["label"]["label"], "just woke: a good time for outdoor light")


if __name__ == "__main__":
    unittest.main()
