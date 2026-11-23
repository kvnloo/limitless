"""Whether live heart data backs the breathing choice: "with live heart data" only when the wearable input is
fresh by the rule limitless_status uses (inputs.json ``ageHours.wearable`` plus the snapshot's age, at most
envelope.STALE_H); otherwise "without heart data". Never a breath count, pace, HR or HRV value. Synthetic only."""
import json
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from limitless import jobs_runner, tools, wind_down  # noqa: E402
from limitless.envelope import STALE_H  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
import test_wind_down_miq as base  # noqa: E402

LINK = "example://breathe"
NOW = base.NOW
H = 3600.0
MIQ, MIQ_Q, CHOICES = base.MIQ, base.MIQ_Q, base.CHOICES
LIVE = "Screens down and lights low when you're ready, or slow breathing in your app (with live heart data): " + LINK
NONE = "Screens down and lights low when you're ready, or slow breathing in your app (without heart data): " + LINK
FIX = ROOT / "tests" / "fixtures" / "state"


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def inputs(wearable, snap_age_h=0.5):
    return {"at": iso(NOW - snap_age_h * H), "ageHours": {"wearable": wearable, "phone": 0.1}}


class Fresh(unittest.TestCase):
    def test_fresh_wearable_is_live(self):
        self.assertTrue(wind_down.wearable_live(inputs(1.0), NOW))
        self.assertEqual(wind_down.wearable_age_h(inputs(1.0), NOW), 1.5)

    def test_the_status_rule_counts_the_snapshot_age(self):
        self.assertTrue(wind_down.wearable_live(inputs(STALE_H - 1, 1.0), NOW))     # exactly STALE_H: recording
        self.assertFalse(wind_down.wearable_live(inputs(STALE_H - 1, 1.5), NOW))

    def test_down_missing_or_broken_is_not_live(self):
        for inp in (None, {}, [], {"ageHours": {}}, inputs("down"), inputs(None), inputs(True), inputs("1.0"),
                    {"ageHours": {"wearable": 1.0}}, {"at": "not a time", "ageHours": {"wearable": 1.0}},
                    inputs(STALE_H + 2)):
            self.assertFalse(wind_down.wearable_live(inp, NOW), inp)

    def test_agrees_with_limitless_status_on_the_fixture(self):
        st = tools.status(StateReader(FIX), NOW)["value"]["inputs"]["wearable"]
        self.assertEqual(wind_down.wearable_live(StateReader(FIX).inputs(), NOW), st["state"] == "recording")
        self.assertEqual(wind_down.wearable_age_h(StateReader(FIX).inputs(), NOW), st["age_h"])


class Words(unittest.TestCase):
    def test_live_and_not(self):
        cfg = {wind_down.BREATHING_KEY: LINK}
        self.assertEqual(wind_down.line(cfg, heart_live=True), LIVE)
        self.assertEqual(wind_down.line(cfg, heart_live=False), NONE)
        self.assertEqual(wind_down.line(cfg), NONE)                                  # unknown is not live
        self.assertEqual(wind_down.line(cfg, heart_live="yes"), NONE)

    def test_no_link_means_no_heart_words(self):
        self.assertEqual(wind_down.line({}, heart_live=True), wind_down.DEFAULT)

    def test_never_a_number(self):
        for live in (True, False):
            got = wind_down.line({wind_down.BREATHING_KEY: LINK, "wind_down_line": "off"}, heart_live=live)
            self.assertEqual(re.findall(r"\d", got), [], got)
            for w in ("bpm", "hrv", "per minute", "breaths", "pace", "heart rate"):
                self.assertNotIn(w, got.lower())


class Miq(unittest.TestCase):
    setUp = base.WindDownRun.setUp
    glide = base.WindDownRun.glide
    sleepmode = base.WindDownRun.sleepmode
    run_ = base.WindDownRun.run_

    def write(self, inp):
        self.cfg.write_text(json.dumps({wind_down.BREATHING_KEY: LINK}))
        if inp is not None:
            (self.st / "inputs.json").write_text(json.dumps(inp))

    def line(self):
        _, push = self.run_()
        lines = dict(push.sent)[MIQ].splitlines()
        self.assertEqual((lines[0], lines[-1], len(lines)), (MIQ_Q, CHOICES, 3))
        return lines[1]

    def test_live_wearable(self):
        self.write(inputs(0.4))
        self.assertEqual(self.line(), LIVE)

    def test_stale_wearable(self):
        self.write(inputs(STALE_H + 3))
        self.assertEqual(self.line(), NONE)

    def test_down_wearable(self):
        self.write(inputs("down"))
        self.assertEqual(self.line(), NONE)

    def test_no_inputs_file(self):
        self.write(None)
        self.assertEqual(self.line(), NONE)

    def test_no_link_no_change(self):
        (self.st / "inputs.json").write_text(json.dumps(inputs(0.4)))
        self.assertEqual(self.line(), base.LINE)

    def test_without_state_dir_is_not_live(self):
        self.write(inputs(0.4))
        evs = jobs_runner.events(jobs_runner.StateReader(self.st), env=self.env, home=self.root)
        self.assertEqual(jobs_runner.miq_wind_down(evs, NOW - 60, self.env, self.root, base.UTC), NONE)
        self.assertEqual(jobs_runner.miq_wind_down(evs, NOW - 60, self.env, self.root, base.UTC,
                                                   state_dir=self.st, now=NOW), LIVE)


if __name__ == "__main__":
    unittest.main()
