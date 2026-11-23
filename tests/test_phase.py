"""phase.phase: the part of the day in words, from the wake event (never a clock), a posture file overriding
only when fresher than the wake and naming a known phase. Synthetic numbers only."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import phase as ph  # noqa: E402

H = 3600.0
WAKE = 1894690680.0   # synthetic epoch seconds; the core never turns it into a time of day
NAMES = {"just_woke", "day", "evening", "asleep", "unknown"}


class Core(unittest.TestCase):
    def test_just_woke_inside_the_light_span(self):
        self.assertEqual(ph.phase(WAKE, WAKE + 0.25 * H, False), "just_woke")

    def test_day_after_the_light_span(self):
        self.assertEqual(ph.phase(WAKE, WAKE + ph.LIGHT_H * H, False), "day")
        self.assertEqual(ph.phase(WAKE, WAKE + 5 * H, False), "day")

    def test_light_span_comes_from_config_hours(self):
        self.assertEqual(ph.phase(WAKE, WAKE + 1.5 * H, False, light_h=2), "just_woke")
        self.assertEqual(ph.phase(WAKE, WAKE + 0.5 * H, False, light_h=0.25), "day")

    def test_bad_light_span_falls_back_to_the_default(self):
        for bad in (None, 0, -1, "two", True, float("nan"), float("inf"), 99):
            self.assertEqual(ph.light_hours(bad), ph.LIGHT_H, bad)
        self.assertLess(ph.LIGHT_H, 3)   # a short span after the wake event

    def test_evening_after_the_wind_down_event(self):
        self.assertEqual(ph.phase(WAKE, WAKE + 15 * H, False, wind_down_at=WAKE + 14 * H), "evening")

    def test_a_wind_down_before_the_wake_is_last_night(self):
        self.assertEqual(ph.phase(WAKE, WAKE + 5 * H, False, wind_down_at=WAKE - 8 * H), "day")

    def test_a_wind_down_after_now_is_not_read(self):
        self.assertEqual(ph.phase(WAKE, WAKE + 5 * H, False, wind_down_at=WAKE + 6 * H), "day")

    def test_asleep_while_sleep_mode_is_on(self):
        self.assertEqual(ph.phase(WAKE, WAKE + 0.1 * H, True), "asleep")
        self.assertEqual(ph.phase(None, WAKE, True), "asleep")

    def test_unknown_without_a_wake_event(self):
        r = ph.resolve(None, WAKE, False)
        self.assertEqual((r["phase"], r["why"]), ("unknown", "no wake event yet"))

    def test_unknown_for_a_wake_after_now_or_too_old(self):
        self.assertEqual(ph.phase(WAKE, WAKE - H, False), "unknown")
        self.assertEqual(ph.phase(WAKE, WAKE + 30 * H, False), "unknown")

    def test_no_clock_time_rule(self):
        # the same span after the wake gives the same phase whatever the wake's time of day
        for shift in range(0, 24):
            w = WAKE + shift * H
            self.assertEqual(ph.phase(w, w + 0.5 * H, False), "just_woke", shift)
            self.assertEqual(ph.phase(w, w + 4 * H, False), "day", shift)

    def test_result_is_always_a_known_name(self):
        for now in (WAKE - H, WAKE, WAKE + H, WAKE + 10 * H, WAKE + 40 * H):
            for on in (True, False):
                self.assertIn(ph.phase(WAKE, now, on), NAMES)


class Posture(unittest.TestCase):
    def test_fresher_posture_with_a_known_name_overrides(self):
        r = ph.resolve(WAKE, WAKE + 5 * H, False, {"phase": "evening", "at": WAKE + 4 * H})
        self.assertEqual((r["phase"], r["source"]), ("evening", "posture"))

    def test_posture_older_than_the_wake_is_ignored_with_a_reason(self):
        r = ph.resolve(WAKE, WAKE + 0.5 * H, False, {"phase": "evening", "at": WAKE - H})
        self.assertEqual((r["phase"], r["source"]), ("just_woke", "wake"))
        self.assertIn("older than the wake event", r["posture_ignored"])

    def test_unknown_posture_name_is_ignored_with_a_reason(self):
        for name in ("subjective_night", "", None, 7, "unknown"):
            r = ph.resolve(WAKE, WAKE + 5 * H, False, {"phase": name, "at": WAKE + 4 * H})
            self.assertEqual((r["phase"], r["source"]), ("day", "wake"), name)
            self.assertIn("not a known phase", r["posture_ignored"])

    def test_posture_names_are_read_loosely(self):
        r = ph.resolve(WAKE, WAKE + 5 * H, False, {"phase": " Just-Woke ", "at": WAKE + 4 * H})
        self.assertEqual(r["phase"], "just_woke")

    def test_extra_posture_fields_are_ignored(self):
        r = ph.resolve(WAKE, WAKE + 5 * H, False, {"phase": "day", "at": WAKE + 4 * H, "x": [1], "v": 3})
        self.assertEqual((r["phase"], r["source"]), ("day", "posture"))

    def test_posture_without_a_time_or_from_the_future_is_ignored(self):
        for bad in ({"phase": "day"}, {"phase": "day", "at": "soon"}, {"phase": "day", "at": WAKE + 9 * H}):
            r = ph.resolve(WAKE, WAKE + 5 * H, False, bad)
            self.assertEqual(r["source"], "wake", bad)
            self.assertTrue(r["posture_ignored"], bad)

    def test_not_an_object_is_ignored(self):
        for bad in ("evening", ["evening"], 3):
            r = ph.resolve(WAKE, WAKE + 5 * H, False, bad)
            self.assertEqual((r["phase"], r["source"]), ("day", "wake"))
            self.assertIn("not an object", r["posture_ignored"])

    def test_posture_without_a_wake_event_still_counts_when_recent(self):
        r = ph.resolve(None, WAKE + 5 * H, False, {"phase": "day", "at": WAKE + 4 * H})
        self.assertEqual((r["phase"], r["source"]), ("day", "posture"))
        r = ph.resolve(None, WAKE + 50 * H, False, {"phase": "day", "at": WAKE})
        self.assertEqual(r["phase"], "unknown")

    def test_live_sleep_mode_beats_a_posture(self):
        r = ph.resolve(WAKE, WAKE + 5 * H, True, {"phase": "day", "at": WAKE + 4 * H})
        self.assertEqual(r["phase"], "asleep")

    def test_why_is_digit_free(self):
        cases = [(None, WAKE, False, None), (WAKE, WAKE + 30 * H, False, None), (WAKE, WAKE - H, False, None),
                 (WAKE, WAKE + 2 * H, False, {"phase": "x", "at": WAKE + H}), (WAKE, WAKE + H, True, None)]
        for c in cases:
            r = ph.resolve(*c)
            text = r["why"] + (r.get("posture_ignored") or "")
            self.assertFalse(any(ch.isdigit() for ch in text), (c, r))


if __name__ == "__main__":
    unittest.main()
