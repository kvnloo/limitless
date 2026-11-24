"""jobs.should_fire: deliver | hold | drop | not_triggered, through decision_window and the send gate.

Synthetic fixtures only. NOW is an arbitrary epoch; only differences between times matter.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import copy
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import decision_window as dw  # noqa: E402
from limitless import jobs  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0
FIX = Path(__file__).resolve().parent / "fixtures" / "state"


def ev(name, ago_h):
    return {"event": name, "at": NOW - ago_h * H}


NIGHT = [ev("sleep_mode_on", 8.5), ev("sleep_mode_off", 0.2)]       # a long on: a wake
NAP = [ev("sleep_mode_off", 5), ev("sleep_mode_on", 0.8), ev("sleep_mode_off", 0.1)]  # a short on: a nap


def st(cls, since="wake"):
    return dw.WindowState(cls=cls, since=since, source="test")


def fire(name, events, state=None, sent=(), now=NOW, spec=None):
    return jobs.should_fire(spec or jobs.SPECS[name], events, state if state is not None else st("anytime"),
                            list(sent), now)


class Triggers(unittest.TestCase):
    def test_no_event_is_not_triggered(self):
        v = fire("wake_brief", [])
        self.assertEqual(v.action, jobs.NOT_TRIGGERED)
        self.assertIn("no wake", v.reason)

    def test_wake_after_long_on_delivers(self):
        v = fire("wake_brief", NIGHT)
        self.assertEqual(v.action, jobs.DELIVER, v.reason)
        self.assertEqual(v.trigger_at, NOW - 0.2 * H)

    def test_explicit_wake_event(self):
        self.assertEqual(fire("wake_brief", [ev("wake", 1)]).action, jobs.DELIVER)

    def test_nap_is_not_a_wake_and_a_night_is_not_a_nap(self):
        self.assertEqual(fire("nap", NAP).action, jobs.DELIVER)
        self.assertEqual(fire("wake_brief", NAP).action, jobs.NOT_TRIGGERED)
        self.assertEqual(fire("nap", NIGHT).action, jobs.NOT_TRIGGERED)

    def test_off_with_no_on_before_it_is_neither(self):
        self.assertEqual(fire("nap", [ev("sleep_mode_off", 1)]).action, jobs.NOT_TRIGGERED)
        self.assertEqual(fire("wake_brief", [ev("sleep_mode_off", 1)]).action, jobs.NOT_TRIGGERED)

    def test_future_events_are_ignored(self):
        self.assertEqual(fire("miq", [ev("wind_down", -1)], st("wind_down")).action, jobs.NOT_TRIGGERED)

    def test_habit_cue(self):
        self.assertEqual(fire("habit_checkin", [ev("habit_cue", 0.1)], st("unknown")).action, jobs.DELIVER)

    def test_sleepmode_rows_from_the_state_dir(self):
        rows = [json.loads(line) for line in (FIX / "sleepmode.jsonl").read_text().splitlines() if line.strip()]
        events = jobs.events_from_sleepmode(rows)
        self.assertEqual([e["event"] for e in events], ["sleep_mode_off", "sleep_mode_on", "sleep_mode_off"])
        last = events[-1]["at"]
        v = jobs.should_fire(jobs.SPECS["wake_brief"], events, st("anytime"), [], last + 600)
        self.assertEqual(v.action, jobs.DELIVER, v.reason)


class Windows(unittest.TestCase):
    def test_asleep_holds(self):
        v = fire("wake_brief", NIGHT, st("asleep"))
        self.assertEqual(v.action, jobs.HOLD)
        self.assertIn("asleep", v.reason)

    def test_window_envelope_from_window_py(self):
        self.assertEqual(fire("wake_brief", NIGHT, {"value": "asleep", "reason": "x"}).action, jobs.HOLD)
        self.assertEqual(fire("miq", [ev("wind_down", 0.1)], {"value": "peak"}).action, jobs.HOLD)

    def test_miq_waits_for_wind_down(self):
        events = [ev("wind_down", 0.1)]
        held = fire("miq", events, st("trough"))
        self.assertEqual(held.action, jobs.HOLD)
        self.assertIn("trough", held.reason)
        self.assertEqual(fire("miq", events, st("wind_down", since="wind_down")).action, jobs.DELIVER)

    def test_peak_wake_brief_holds_outside_peak(self):
        spec = jobs.wake_brief(decision=True)
        self.assertEqual(fire("", NIGHT, st("anytime"), spec=spec).action, jobs.HOLD)
        self.assertEqual(fire("", NIGHT, st("peak"), spec=spec).action, jobs.DELIVER)

    def test_unknown_window_holds_a_windowed_job(self):
        self.assertEqual(fire("miq", [ev("wind_down", 0.1)], st("unknown")).action, jobs.HOLD)


class Limits(unittest.TestCase):
    def test_once_per_window(self):
        trig = NOW - 0.2 * H
        sent = [jobs.sent_entry(jobs.SPECS["wake_brief"], trig, NOW - 0.1 * H)]
        v = fire("wake_brief", NIGHT, sent=sent)
        self.assertEqual(v.action, jobs.DROP)
        self.assertIn("once", v.reason)

    def test_a_send_before_this_wake_does_not_count(self):
        yesterday = jobs.sent_entry(jobs.SPECS["wake_brief"], NOW - 24 * H, NOW - 23.9 * H)
        self.assertEqual(fire("wake_brief", NIGHT, sent=[yesterday]).action, jobs.DELIVER)

    def test_peak_budget_is_the_job_budget(self):
        spec = jobs.wake_brief(decision=True)
        sent = [jobs.sent_entry(spec, NOW - 0.2 * H, NOW - 0.1 * H)]
        self.assertEqual(fire("", NIGHT, st("peak"), sent=sent, spec=spec).action, jobs.DROP)

    def test_send_gate_dedupe(self):
        trig = NOW - 0.2 * H
        sent = [{"t": NOW - 0.1 * H, "k": jobs.dedupe_key(jobs.SPECS["wake_brief"], trig)}]  # no job field
        v = fire("wake_brief", NIGHT, sent=sent)
        self.assertEqual(v.action, jobs.DROP)
        self.assertIn("12 h", v.reason)

    def test_daily_cap_holds(self):
        sent = [{"t": NOW - i * H, "k": f"k{i}"} for i in range(1, 7)]
        v = fire("wake_brief", NIGHT, sent=sent)
        self.assertEqual(v.action, jobs.HOLD)
        self.assertIn("cap", v.reason)

    def test_expired_by_the_next_sleep(self):
        v = fire("miq", [ev("wind_down", 2), ev("sleep_mode_on", 1)], st("wind_down"))
        self.assertEqual(v.action, jobs.DROP)
        self.assertIn("expired", v.reason)

    def test_stale_trigger_is_missing_data(self):
        v = fire("habit_checkin", [ev("habit_cue", 30)])
        self.assertEqual(v.action, jobs.DROP)
        self.assertIn("old", v.reason)


class Visibility(unittest.TestCase):
    def test_hold_is_visible_and_not_counted_as_sent(self):
        events, sent = [ev("wind_down", 0.1)], []
        held = jobs.should_fire(jobs.SPECS["miq"], events, st("peak"), sent, NOW)
        self.assertEqual(held.action, jobs.HOLD)
        self.assertTrue(held.reason)
        self.assertEqual(sent, [])
        later = jobs.should_fire(jobs.SPECS["miq"], events, st("wind_down"), sent, NOW + 600)
        self.assertEqual(later.action, jobs.DELIVER)

    def test_pure_and_one_line_reasons(self):
        cases = [("wake_brief", [], st("anytime")), ("wake_brief", NIGHT, st("asleep")),
                 ("miq", [ev("wind_down", 0.1)], st("wind_down")), ("nap", NAP, None),
                 ("miq", [ev("wind_down", 2), ev("sleep_mode_on", 1)], st("wind_down"))]
        for name, events, state in cases:
            before = copy.deepcopy(events)
            v = jobs.should_fire(jobs.SPECS[name], events, state, [], NOW)
            self.assertIn(v.action, jobs.ACTIONS)
            self.assertTrue(v.reason and "\n" not in v.reason, v)
            self.assertEqual(events, before)


if __name__ == "__main__":
    unittest.main()
