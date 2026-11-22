"""wake_proxy.events_from_screen: a fallback wake event from phone screen events when Sleep mode is not used.

Synthetic rows only. T0 is an arbitrary epoch; only differences between times matter.
"""
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, wake_proxy  # noqa: E402

T0 = 2_000_000_000.0
H = 3600.0
SRC = Path(__file__).resolve().parents[1] / "limitless" / "wake_proxy.py"


def row(at_h, typ, pkg="com.example.launcher"):
    return {"ts": int((T0 + at_h * H) * 1000), "type": typ, "pkg": pkg}


EVENING = [row(0, "SCREEN_INTERACTIVE"), row(0.01, "KEYGUARD_HIDDEN"), row(0.2, "USER_INTERACTION"),
           row(0.5, "SCREEN_NON_INTERACTIVE"), row(0.51, "KEYGUARD_SHOWN")]
NIGHT_PINGS = [row(2, "NOTIFICATION_INTERRUPTION", "com.example.chat"),
               row(4, "NOTIFICATION_INTERRUPTION", "com.example.mail")]
MORNING = [row(8, "SCREEN_INTERACTIVE"), row(8.01, "KEYGUARD_HIDDEN"), row(8.05, "USER_INTERACTION"),
           row(8.3, "USER_INTERACTION")]


class EventsFromScreen(unittest.TestCase):
    def test_wake_after_a_long_quiet_gap(self):
        evs = wake_proxy.events_from_screen(EVENING + NIGHT_PINGS + MORNING)
        self.assertEqual(len(evs), 1)
        e = evs[0]
        self.assertEqual(e["event"], "wake")
        self.assertEqual(e["at"], T0 + 8.01 * H)          # the first KEYGUARD_HIDDEN after the gap
        self.assertEqual(e["source"], "screen")
        self.assertLess(e["confidence"], jobs.SLEEP_MODE_CONFIDENCE)
        self.assertGreater(e["confidence"], 0)
        self.assertEqual(e["gap_from"], T0 + 0.2 * H)     # the last person event before the gap

    def test_notifications_are_not_the_person(self):
        # Pings in the night do not split the gap; a ping alone never makes a wake.
        self.assertEqual(len(wake_proxy.events_from_screen(EVENING + NIGHT_PINGS + MORNING)), 1)
        self.assertEqual(wake_proxy.events_from_screen(NIGHT_PINGS), [])
        self.assertEqual(wake_proxy.events_from_screen(EVENING + [row(9, "NOTIFICATION_INTERRUPTION")]), [])

    def test_screen_on_without_unlock_is_not_a_wake(self):
        # A screen lit by a notification, then dark again: no unlock, no interaction, no wake.
        rows = EVENING + [row(8, "SCREEN_INTERACTIVE"), row(8.01, "SCREEN_NON_INTERACTIVE")]
        self.assertEqual(wake_proxy.events_from_screen(rows), [])

    def test_user_interaction_counts_too(self):
        rows = EVENING + [row(7, "USER_INTERACTION")]
        self.assertEqual([e["at"] for e in wake_proxy.events_from_screen(rows)], [T0 + 7 * H])

    def test_short_gap_is_not_a_wake(self):
        rows = EVENING + [row(2, "KEYGUARD_HIDDEN"), row(2.1, "USER_INTERACTION")]
        self.assertEqual(wake_proxy.events_from_screen(rows), [])
        self.assertEqual(len(wake_proxy.events_from_screen(rows, min_gap_s=1 * H)), 1)

    def test_min_gap_is_a_duration(self):
        # The same gap anywhere on the clock gives the same answer: shift every row by odd offsets.
        for shift_h in (0, 3.25, 7.5, 13, 19.75):
            rows = [dict(r, ts=r["ts"] + int(shift_h * H * 1000)) for r in EVENING + MORNING]
            evs = wake_proxy.events_from_screen(rows)
            self.assertEqual([e["at"] for e in evs], [T0 + (8.01 + shift_h) * H], shift_h)

    def test_first_event_without_history_is_not_a_wake(self):
        # No person event before it: the gap is unknown, so there is no wake.
        self.assertEqual(wake_proxy.events_from_screen(MORNING), [])

    def test_two_nights(self):
        daytime = [row(8.3 + 2.5 * i, "USER_INTERACTION") for i in range(1, 7)]   # use every 2.5 h
        day2 = [dict(r, ts=r["ts"] + int(24 * H * 1000)) for r in EVENING + MORNING]
        evs = wake_proxy.events_from_screen(EVENING + MORNING + daytime + day2)
        self.assertEqual([e["at"] for e in evs], [T0 + 8.01 * H, T0 + 32.01 * H])

    def test_unsorted_and_malformed_rows(self):
        junk = [None, "x", {}, {"ts": "soon", "type": "KEYGUARD_HIDDEN"}, {"ts": True, "type": "USER_INTERACTION"},
                {"ts": T0 * 1000, "type": "SOMETHING_ELSE"}]
        rows = list(reversed(EVENING + MORNING)) + junk
        self.assertEqual([e["at"] for e in wake_proxy.events_from_screen(rows)], [T0 + 8.01 * H])

    def test_default_gap_is_a_few_hours(self):
        self.assertGreaterEqual(wake_proxy.MIN_GAP_S, jobs.NAP_MAX_S)
        self.assertLessEqual(wake_proxy.MIN_GAP_S, 8 * H)

    def test_no_hour_of_day_constant(self):
        src = SRC.read_text()
        self.assertIsNone(re.search(r"\b\d{1,2}:\d{2}\b|\b\d{1,2}\s*(am|pm)\b", src, re.I))
        self.assertIsNone(re.search(r"\.hour\b|\.tm_hour\b|localtime|strftime|fromtimestamp|datetime", src))
        self.assertIsNone(re.search(r"(?i)hour_of_day|time_of_day|morning|night_start|bedtime_h", src))


class ReadFromStateDir(unittest.TestCase):
    def test_screen_events_file_to_wake(self):
        import json
        import tempfile
        from limitless.state_reader import StateReader
        with tempfile.TemporaryDirectory() as d:
            text = "\n".join(json.dumps(r) for r in EVENING + NIGHT_PINGS + MORNING) + "\n{broken\n"
            (Path(d) / "screen-events.jsonl").write_text(text)
            rows = StateReader(Path(d)).screen_events()
            self.assertEqual(StateReader(Path(d) / "absent").screen_events(), [])
        self.assertEqual(len(rows), len(EVENING + NIGHT_PINGS + MORNING))
        self.assertEqual([e["at"] for e in wake_proxy.events_from_screen(rows)], [T0 + 8.01 * H])


if __name__ == "__main__":
    unittest.main()
