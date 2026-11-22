"""jobs.merged_events: Sleep-mode events plus the screen-event wake fallback, and the habit cue after a wake.

Synthetic fixtures only. NOW is an arbitrary epoch; only differences between times matter.
"""
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import decision_window as dw  # noqa: E402
from limitless import jobs, wake_proxy  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0


def at(ago_h):
    return NOW - ago_h * H


def sleep(on_ago, off_ago=None):
    out = [{"event": "sleep_mode_on", "at": at(on_ago)}]
    if off_ago is not None:
        out.append({"event": "sleep_mode_off", "at": at(off_ago)})
    return out


def swake(ago_h, gap_h=8.0):
    return {"event": "wake", "at": at(ago_h), "gap_from": at(ago_h + gap_h), "source": "screen",
            "confidence": wake_proxy.SCREEN_CONFIDENCE}


def wakes(events):
    return [e for e in events if e["event"] == "wake"]


def fire(name, events, now=NOW):
    return jobs.should_fire(jobs.SPECS[name], events, dw.WindowState("anytime", source="test"), [], now)


class Merge(unittest.TestCase):
    def test_screen_wake_is_used_without_sleep_mode(self):
        m = jobs.merged_events([], [swake(0.5)])
        self.assertEqual([(e["at"], e["source"]) for e in wakes(m)], [(at(0.5), "screen")])
        self.assertEqual(fire("wake_brief", []).action, jobs.NOT_TRIGGERED)
        v = fire("wake_brief", m)
        self.assertEqual((v.action, v.trigger_at), (jobs.DELIVER, at(0.5)))

    def test_sleep_mode_wake_wins_in_the_same_gap(self):
        night = sleep(8.6, 0.4)                          # on/off inside the screen gap (8.5 h .. 0.5 h ago)
        m = jobs.merged_events(night, [swake(0.5)])
        self.assertEqual(wakes(m), [])                   # the wake is the Sleep-mode off, as before
        v = fire("wake_brief", m)
        self.assertEqual((v.action, v.trigger_at), (jobs.DELIVER, at(0.4)))

    def test_sleep_mode_off_just_after_the_unlock_is_the_same_gap(self):
        m = jobs.merged_events(sleep(8.6, 0.3), [swake(0.5)])
        self.assertEqual(wakes(m), [])
        self.assertEqual(fire("wake_brief", m).trigger_at, at(0.3))

    def test_last_nights_sleep_mode_does_not_hide_tonights_screen_wake(self):
        old = sleep(33, 25)                              # a Sleep-mode night a day earlier
        m = jobs.merged_events(old, [swake(25.2, 7), swake(0.5)])
        self.assertEqual([e["at"] for e in wakes(m)], [at(0.5)])
        self.assertEqual(fire("wake_brief", m).trigger_at, at(0.5))

    def test_sleep_mode_still_on_does_not_block_the_screen_wake(self):
        m = jobs.merged_events(sleep(8.6), [swake(0.5)])     # no off yet: there is no Sleep-mode wake
        self.assertEqual([e["at"] for e in wakes(m)], [at(0.5)])

    def test_a_nap_stays_sleep_mode_only(self):
        nap = sleep(1.5, 0.6)                            # a short on: a nap
        m = jobs.merged_events(nap, [swake(0.5, gap_h=4.5)])
        self.assertEqual(wakes(m), [])                   # the quiet gap held a nap, not a night
        self.assertEqual(fire("nap", m).action, jobs.DELIVER)
        self.assertEqual(fire("wake_brief", m).action, jobs.NOT_TRIGGERED)
        # A screen wake never makes a nap.
        self.assertEqual(fire("nap", jobs.merged_events([], [swake(0.5)])).action, jobs.NOT_TRIGGERED)

    def test_inputs_are_not_changed_and_output_is_sorted(self):
        night, screen = sleep(8.6, 0.4), [swake(0.5)]
        before = (repr(night), repr(screen))
        m = jobs.merged_events(night, screen)
        self.assertEqual((repr(night), repr(screen)), before)
        self.assertEqual([e["at"] for e in m], sorted(e["at"] for e in m))


class HabitCue(unittest.TestCase):
    def cues(self, m):
        return [e for e in m if e["event"] == "habit_cue"]

    def test_cue_one_hour_after_a_screen_wake(self):
        m = jobs.merged_events([], [swake(3)])
        self.assertEqual([e["at"] for e in self.cues(m)], [at(3) + jobs.HABIT_CUE_AFTER_S])
        self.assertEqual(jobs.HABIT_CUE_AFTER_S, 1 * H)
        self.assertEqual(self.cues(m)[0]["source"], "screen")

    def test_cue_one_hour_after_a_sleep_mode_wake(self):
        m = jobs.merged_events(sleep(10, 3), [])
        self.assertEqual([e["at"] for e in self.cues(m)], [at(2)])
        self.assertEqual(self.cues(m)[0]["source"], "sleep_mode")
        self.assertEqual(self.cues(m)[0]["confidence"], jobs.SLEEP_MODE_CONFIDENCE)

    def test_no_cue_after_a_nap(self):
        self.assertEqual(self.cues(jobs.merged_events(sleep(1.5, 1.2), [])), [])

    def test_checkin_waits_for_the_first_hour(self):
        m = jobs.merged_events([], [swake(0.5)])
        self.assertEqual(fire("habit_checkin", m).action, jobs.NOT_TRIGGERED)   # cue is 30 min away
        v = fire("habit_checkin", m, now=NOW + 0.6 * H)
        self.assertEqual((v.action, v.trigger_at), (jobs.DELIVER, at(0.5) + H))

    def test_cue_is_a_duration_from_the_event(self):
        for shift_h in (0, 5.5, 11, 17.25):
            m = jobs.merged_events([], [swake(3 + shift_h)])
            self.assertEqual(self.cues(m)[0]["at"] - wakes(m)[0]["at"], H)

    def test_no_clock_constant_in_jobs(self):
        text = Path(jobs.__file__).read_text()
        self.assertIsNone(re.search(r"\b\d{1,2}:\d{2}\b|\.hour\b|localtime|strftime", text))


if __name__ == "__main__":
    unittest.main()
