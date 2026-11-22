"""A late message is noise: each job drops once its trigger is older than its stale_after_s.

Durations only (no time of day). Synthetic epochs; only differences matter.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs  # noqa: E402

T0 = 2_000_000_000.0
H = 3600.0
AWAKE = {"cls": "anytime", "confidence": 1.0}


def verdict(spec, trig_event, age_h):
    return jobs.should_fire(spec, [{"event": trig_event, "at": T0}], AWAKE, [], T0 + age_h * H)


class StaleAfter(unittest.TestCase):
    def test_wake_brief_delivers_soon_after_the_wake(self):
        self.assertEqual(verdict(jobs.WAKE_BRIEF, "wake", 0.5).action, jobs.DELIVER)

    def test_wake_brief_drops_hours_after_the_wake(self):
        v = verdict(jobs.WAKE_BRIEF, "wake", 9.7)
        self.assertEqual(v.action, jobs.DROP, v)
        self.assertIn("late", v.reason)

    def test_habit_checkin_drops_hours_after_its_cue(self):
        self.assertEqual(verdict(jobs.HABIT_CHECKIN, "habit_cue", 8.7).action, jobs.DROP)
        self.assertEqual(verdict(jobs.HABIT_CHECKIN, "habit_cue", 0.5).action, jobs.DELIVER)

    def test_builders_keep_the_limit(self):
        self.assertEqual(jobs.wake_brief(decision=True).stale_after_s, jobs.WAKE_BRIEF.stale_after_s)
        habit = jobs.habit_checkin({"cue": "focus_end"})
        self.assertEqual(habit.stale_after_s, jobs.HABIT_CHECKIN.stale_after_s)

    def test_every_send_job_has_a_limit_under_the_awake_cap(self):
        for spec in jobs.SPECS.values():
            self.assertIsNotNone(spec.stale_after_s, spec.name)
            self.assertGreater(spec.stale_after_s, 0)
            self.assertLess(spec.stale_after_s, jobs.MAX_AWAKE_H * H)

    def test_limit_must_be_positive(self):
        with self.assertRaises(ValueError):
            jobs.JobSpec("x", "wake", "anytime", "X", 1, "sleep_mode_on", stale_after_s=0)


if __name__ == "__main__":
    unittest.main()
