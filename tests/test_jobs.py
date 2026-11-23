"""limitless.jobs: event-triggered job specs through the decision window and the send gate.

Synthetic fixtures only. Times are epoch seconds picked for the test; nothing reads the clock.
"""
import dataclasses
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs  # noqa: E402

CRON = re.compile(r"^\s*(@(yearly|annually|monthly|weekly|daily|hourly|reboot)|(\S+\s+){4}\S+)\s*$")
CLOCK = re.compile(r"\b\d{1,2}:\d{2}\b|\b\d{1,2}\s*(am|pm)\b", re.I)
TIME_FIELD = re.compile(r"(?i)hour|minute|cron|clock|time_of_day|\bat\b")


class Specs(unittest.TestCase):
    def test_five_specs_by_name(self):
        self.assertEqual(sorted(jobs.SPECS), ["habit_checkin", "miq", "nap", "wake_brief", "week_review"])
        for name, spec in jobs.SPECS.items():
            self.assertIsInstance(spec, jobs.JobSpec)
            self.assertEqual(spec.name, name)

    def test_fields(self):
        names = [f.name for f in dataclasses.fields(jobs.JobSpec)]
        for f in ("name", "trigger_event", "window_class", "send_title", "max_per_window", "expires"):
            self.assertIn(f, names)

    def test_each_spec(self):
        s = jobs.SPECS
        self.assertEqual((s["wake_brief"].trigger_event, s["wake_brief"].window_class), ("wake", "anytime"))
        self.assertEqual(s["wake_brief"].send_title, "Wake-up brief")
        self.assertEqual((s["nap"].trigger_event, s["nap"].trigger_after), ("sleep_mode_off", "short_on"))
        self.assertEqual(s["nap"].send_title, "Back from nap")
        self.assertEqual((s["miq"].trigger_event, s["miq"].window_class), ("wind_down", "wind_down"))
        self.assertEqual(s["miq"].send_title, "MIQ for tonight?")
        self.assertEqual((s["habit_checkin"].trigger_event, s["habit_checkin"].window_class),
                         ("habit_cue", "anytime"))
        self.assertEqual(s["habit_checkin"].answers, ("Done", "No", "Skip"))
        for spec in s.values():
            self.assertEqual(spec.max_per_window, 1)
            self.assertIn(spec.expires, jobs.EVENTS)

    def test_wake_brief_with_a_decision_is_peak(self):
        self.assertEqual(jobs.wake_brief(decision=True).window_class, "peak")
        self.assertEqual(jobs.wake_brief(decision=False), jobs.SPECS["wake_brief"])

    def test_triggers_are_events_only(self):
        for spec in jobs.SPECS.values():
            self.assertIn(spec.trigger_event, jobs.EVENTS)
            for f in dataclasses.fields(spec):
                self.assertIsNone(TIME_FIELD.search(f.name), f"{spec.name}.{f.name} is a clock field")
                for v in (lambda x: x if isinstance(x, tuple) else (x,))(getattr(spec, f.name)):
                    if isinstance(v, str):
                        self.assertIsNone(CRON.match(v), f"{spec.name}.{f.name} looks like cron: {v!r}")
                        self.assertIsNone(CLOCK.search(v), f"{spec.name}.{f.name} has a clock time: {v!r}")

    def test_clock_detector_catches_clock_specs(self):
        # Guard the guard: the checks above must fail on a clock-based spec.
        self.assertTrue(CRON.match("30 7 * * *") and CRON.match("@daily"))
        self.assertTrue(CLOCK.search("07:30") and CLOCK.search("9 pm"))
        self.assertTrue(TIME_FIELD.search("run_hour") and TIME_FIELD.search("minute"))

    def test_bad_spec_is_a_config_error(self):
        with self.assertRaises(ValueError):
            jobs.JobSpec("x", "07:30", "anytime", "X", 1, "sleep_mode_on")
        with self.assertRaises(ValueError):
            jobs.JobSpec("x", "wake", "evening", "X", 1, "sleep_mode_on")
        with self.assertRaises(ValueError):
            jobs.JobSpec("x", "wake", "anytime", "X", 0, "sleep_mode_on")

    def test_habit_cue_from_habit_json(self):
        self.assertEqual(jobs.habit_checkin({"habit": "h", "cue": "wind_down"}).trigger_event, "wind_down")
        self.assertEqual(jobs.habit_checkin({"habit": "h"}).trigger_event, "habit_cue")
        # A clock time is not a cue: fall back to the explicit habit_cue event.
        self.assertEqual(jobs.habit_checkin({"habit": "h", "cue": "21:30"}).trigger_event, "habit_cue")
        self.assertEqual(jobs.habit_checkin(None), jobs.SPECS["habit_checkin"])


if __name__ == "__main__":
    unittest.main()
