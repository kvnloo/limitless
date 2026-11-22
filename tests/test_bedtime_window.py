"""The bedtime question (a ``wind_down`` job) delivers only when the window chain says wind_down,
whatever hour of the day the Glide fixture's events fall on. Synthetic fixtures only."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import decision_window as dw  # noqa: E402
from limitless import send_gate as g  # noqa: E402
from limitless import window_chain as wc  # noqa: E402
from limitless.glide_provider import GlideProvider  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "glide"
ANCHOR = 1894708800.0
H = 3600.0
JOB = "wind_down"  # the bedtime question's window_class


def shifted(name, delta):
    text = (FIX / name).read_text()
    try:
        data = json.loads(text)
    except ValueError:
        return text  # malformed stays malformed
    if data.get("block"):
        data["block"]["start"] += delta
        data["block"]["end"] += delta
    for item in data.get("queue", []):
        item["at"] += delta
    if data.get("resume"):
        data["resume"]["saved"] += delta
    return json.dumps(data)


def iso(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def sleep_events(now, asleep):
    rows = [{"at": iso(now - 30 * H), "on": True}, {"at": iso(now - 14 * H), "on": False}]
    if asleep:
        rows.append({"at": iso(now - 600), "on": True})
    return wc.EventProvider(rows, {"at": iso(now - 60), "ok": True}, None, now=now)


class BedtimeQuestion(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)

    def run_job(self, fixture, hour, asleep=False, minutes_after=20):
        """Place the fixture's event at `hour` (UTC) of the anchor day, then gate the job."""
        day0 = ANCHOR - (ANCHOR % 86400)
        delta = day0 + hour * H - ANCHOR
        now = ANCHOR + delta + minutes_after * 60
        path = Path(self._d.name) / f"{fixture}-{hour}.json"
        path.write_text(shifted(fixture, delta))
        events = sleep_events(now, asleep)
        state = wc.first_known(GlideProvider(str(path), now=now), events)
        decision = dw.decide(JOB, state, budget_left=1, asleep=events.asleep)
        gate = g.decide("limitless", "Bedtime question", "Anything to capture before tomorrow?", "decision",
                        now, [], events.asleep, window=dw.JobWindow(JOB, state, 1))
        return state, decision, gate

    def test_delivers_only_when_the_chain_says_wind_down_at_every_hour(self):
        fixtures = ("wind-down.json", "focus-block.json", "idle.json", "malformed.json")
        for hour in range(24):
            for fixture in fixtures:
                state, decision, gate = self.run_job(fixture, hour)
                said_wind_down = state.cls == "wind_down"
                self.assertEqual(said_wind_down, fixture == "wind-down.json", (fixture, hour))
                self.assertEqual(decision.action == "deliver", said_wind_down, (fixture, hour, decision))
                self.assertEqual(gate == "send", said_wind_down, (fixture, hour, gate))

    def test_a_morning_wind_down_still_delivers_and_an_evening_without_one_holds(self):
        self.assertEqual(self.run_job("wind-down.json", 9)[1].action, "deliver")
        self.assertEqual(self.run_job("idle.json", 22)[1].action, "hold")

    def test_stale_wind_down_holds(self):
        _, decision, _ = self.run_job("wind-down.json", 21, minutes_after=5 * 60)
        self.assertEqual(decision.action, "hold")

    def test_asleep_holds_even_in_wind_down(self):
        state, decision, gate = self.run_job("wind-down.json", 23, asleep=True)
        self.assertEqual(state.cls, "wind_down")
        self.assertEqual((decision.action, gate), ("hold", "hold"))


if __name__ == "__main__":
    unittest.main()
