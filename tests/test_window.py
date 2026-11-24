"""limitless_window: peak|trough|anytime|asleep from state events (Sleep mode, unlocks), never a clock rule."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import window as w  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
NOW = 1894708800.0
H = 3600.0


def iso(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def events(now, woke_h_ago=None, asleep_h_ago=None, poll_s_ago=60, unlock_h_ago=None):
    """Synthetic event set relative to `now`. Returns (sleep_rows, poll, last_unlock)."""
    rows = [{"at": iso(now - 30 * H), "on": True}]
    if woke_h_ago is not None:
        rows.append({"at": iso(now - woke_h_ago * H), "on": False})
    if asleep_h_ago is not None:
        rows.append({"at": iso(now - asleep_h_ago * H), "on": True})
    poll = None if poll_s_ago is None else {"at": iso(now - poll_s_ago), "ok": True}
    unlock = None if unlock_h_ago is None else {"at": iso(now - unlock_h_ago * H)}
    return rows, poll, unlock


def cls(now=NOW, **kw):
    return w.classify(*events(now, **kw), now=now)["value"]


class Classify(unittest.TestCase):
    def test_sleep_mode_on_is_asleep(self):
        self.assertEqual(cls(woke_h_ago=20, asleep_h_ago=2), "asleep")

    def test_bands_follow_hours_since_the_wake_event(self):
        self.assertEqual(cls(woke_h_ago=0.5), "anytime")   # waking up: capture only
        self.assertEqual(cls(woke_h_ago=3), "peak")
        self.assertEqual(cls(woke_h_ago=7), "trough")
        self.assertEqual(cls(woke_h_ago=11), "anytime")

    def test_same_events_at_any_clock_time_give_the_same_class(self):
        for shift_h in range(0, 24, 5):
            now = NOW + shift_h * H
            for woke in (0.5, 3, 7, 11):
                self.assertEqual(cls(now=now, woke_h_ago=woke), cls(woke_h_ago=woke), (shift_h, woke))

    def test_no_events_is_unknown_at_every_hour(self):
        for shift_h in range(24):
            env = w.classify([], None, None, now=NOW + shift_h * H)
            self.assertEqual(env["value"], "unknown")
            self.assertTrue(env["reason"])

    def test_stale_poll_and_no_recent_unlock_is_unknown(self):
        self.assertEqual(cls(woke_h_ago=3, poll_s_ago=3 * H), "unknown")
        self.assertEqual(cls(woke_h_ago=20, asleep_h_ago=2, poll_s_ago=None), "unknown")

    def test_recent_unlock_shows_awake_when_the_poll_is_stale(self):
        self.assertEqual(cls(woke_h_ago=3, poll_s_ago=None, unlock_h_ago=0.1), "peak")

    def test_awake_without_a_wake_event_is_unknown(self):
        rows = [{"at": iso(NOW - 5 * H), "on": False}]  # off with no preceding on: not a wake
        self.assertEqual(w.classify(rows, {"at": iso(NOW - 60), "ok": True}, None, now=NOW)["value"], "unknown")

    def test_a_very_old_wake_is_unknown(self):
        self.assertEqual(cls(woke_h_ago=22), "unknown")

    def test_a_wake_event_in_the_future_is_unknown(self):
        self.assertEqual(cls(woke_h_ago=-2), "unknown")  # clock skew between hosts, not a band

    def test_envelope_is_a_proxy(self):
        env = w.classify(*events(NOW, woke_h_ago=3), now=NOW)
        self.assertEqual(env["modality"], "proxy")
        self.assertEqual(env["evidence_tier"], "indirect")
        self.assertIn("wake", env["reason"])

    def test_bands_are_configurable(self):
        bands = {"peak": [2, 4], "trough": [4, 8]}
        self.assertEqual(w.classify(*events(NOW, woke_h_ago=5), now=NOW, bands=bands)["value"], "trough")

    def test_fixture(self):
        env = w.window(StateReader(FIX), NOW)
        self.assertEqual(env["value"], "peak")  # woke 06:58Z, 5.0 h before the fixture clock
        self.assertEqual(env["age_h"], 0.0)


if __name__ == "__main__":
    unittest.main()
