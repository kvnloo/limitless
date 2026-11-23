"""The MIQ key is one per local night: `miq:<night date>`, whoever sends and however many wind-downs.

The night is the local date of the evening: an event after midnight and before the person's next
wake belongs to the previous date. The wake is the latest wake event (Sleep mode, screen wake or an
events.jsonl row) at most window.MAX_AWAKE_H before the event; with none, the event's own date.
Times are fixed synthetic epochs in UTC (tz=timezone.utc); nothing sends: the push is a fake.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, jobs_runner  # noqa: E402

UTC = timezone.utc


def t(day, hour, minute=0):
    """Epoch seconds for a synthetic UTC day of May 2033 and hour."""
    return datetime(2033, 5, day, hour, minute, tzinfo=UTC).timestamp()


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class OncePush:
    def __init__(self):
        self.calls = []

    def __call__(self, title, body, once=None):
        self.calls.append((title, body, once))
        return "telegram"


class NightDate(unittest.TestCase):
    def night(self, evs, at, tz=UTC):
        return jobs_runner.night_date(evs, at, tz=tz)

    def test_evening_is_its_own_date(self):
        evs = [{"event": "wake", "at": t(17, 7)}, {"event": "wind_down", "at": t(17, 22)}]
        self.assertEqual(self.night(evs, t(17, 22)), "2033-05-17")

    def test_after_midnight_before_the_next_wake_is_the_previous_date(self):
        evs = [{"event": "wake", "at": t(17, 7)}, {"event": "wind_down", "at": t(18, 1)}]
        self.assertEqual(self.night(evs, t(18, 1)), "2033-05-17")

    def test_the_next_wake_starts_a_new_night(self):
        evs = [{"event": "wake", "at": t(17, 7)}, {"event": "wake", "at": t(18, 7)}]
        self.assertEqual(self.night(evs, t(18, 21)), "2033-05-18")

    def test_a_sleep_mode_wake_counts(self):
        evs = jobs.events_from_sleepmode([{"at": t(16, 23), "on": True}, {"at": t(17, 7), "on": False}])
        self.assertEqual(self.night(evs, t(18, 0, 30)), "2033-05-17")

    def test_a_nap_is_not_a_wake(self):
        evs = [{"event": "wake", "at": t(17, 7)}, {"event": "sleep_mode_on", "at": t(18, 0, 10)},
               {"event": "sleep_mode_off", "at": t(18, 0, 50)}]
        self.assertEqual(self.night(evs, t(18, 1)), "2033-05-17")

    def test_no_wake_is_the_event_date(self):
        self.assertEqual(self.night([], t(17, 22)), "2033-05-17")
        self.assertEqual(self.night([], t(18, 1)), "2033-05-18")

    def test_a_wake_older_than_max_awake_is_missing_data(self):
        evs = [{"event": "wake", "at": t(16, 7)}]
        self.assertEqual(self.night(evs, t(17, 22)), "2033-05-17")
        self.assertEqual(self.night(evs, t(17, 4)), "2033-05-17")

    def test_a_later_wake_does_not_move_an_earlier_event(self):
        evs = [{"event": "wake", "at": t(17, 7)}, {"event": "wake", "at": t(18, 7)}]
        self.assertEqual(self.night(evs, t(18, 1)), "2033-05-17")

    def test_the_local_zone_decides_the_date(self):
        plus3 = timezone(timedelta(hours=3))
        self.assertEqual(self.night([], t(17, 22), tz=plus3), "2033-05-18")
        self.assertEqual(self.night([{"event": "wake", "at": t(17, 4)}], t(17, 22), tz=plus3), "2033-05-17")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.att = self.root / "attention.json"
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json"), "LIMITLESS_GLIDE_ATTENTION": str(self.att)}

    def tearDown(self):
        self.tmp.cleanup()

    def events(self, rows):
        write_rows(self.st / "events.jsonl", rows)

    def window_open(self, saved):
        self.att.write_text(json.dumps({"block": None, "queue": [], "resume": {"saved": saved}, "nudged": ""}))

    def key(self, now, job="miq"):
        return jobs_runner.event_key(self.st, now, job=job, env=self.env, home=self.root, tz=UTC)

    def night_key(self, now, st=None):
        return jobs_runner.night_key(st or self.st, now, env=self.env, home=self.root, tz=UTC)

    def pushed(self, now):
        push = OncePush()
        jobs_runner.run_once(self.st, now, push=push, dry_run=False, env=self.env, home=self.root, tz=UTC)
        return [c[2] for c in push.calls if c[0] == jobs.MIQ.send_title]


class EventKey(Base):
    def test_evening_wind_down_is_the_night_key_and_run_once_pushes_it(self):
        self.events([{"event": "wake", "at": t(17, 7)}, {"event": "wind_down", "at": t(17, 22)}])
        self.window_open(t(17, 22))
        now = t(17, 22, 5)
        self.assertEqual(self.key(now), "miq:2033-05-17")
        self.assertEqual(self.pushed(now), ["miq:2033-05-17"])

    def test_after_midnight_wind_down_keys_the_previous_night(self):
        self.events([{"event": "wake", "at": t(17, 7)}, {"event": "wind_down", "at": t(18, 0, 30)}])
        self.window_open(t(18, 0, 30))
        now = t(18, 0, 35)
        self.assertEqual(self.key(now), "miq:2033-05-17")
        self.assertEqual(self.pushed(now), ["miq:2033-05-17"])

    def test_two_wind_downs_in_one_night_share_the_key(self):
        self.events([{"event": "wake", "at": t(17, 7)}, {"event": "wind_down", "at": t(17, 21)},
                     {"event": "wind_down", "at": t(17, 23, 30)}])
        self.window_open(t(17, 23, 30))
        self.assertEqual({self.key(t(17, 21, 5)), self.key(t(17, 23, 35)), self.key(t(18, 0, 15))},
                         {"miq:2033-05-17"})

    def test_last_nights_wind_down_is_no_key_tonight(self):
        self.events([{"event": "wake", "at": t(16, 7)}, {"event": "wind_down", "at": t(16, 22)},
                     {"event": "wake", "at": t(17, 7)}])
        self.assertIsNone(self.key(t(17, 21)))

    def test_no_wind_down_is_no_key(self):
        self.events([{"event": "wake", "at": t(17, 7)}])
        self.assertIsNone(self.key(t(17, 21)))

    def test_other_jobs_keep_their_event_time_keys(self):
        self.events([{"event": "wake", "at": t(17, 7)}])
        self.assertEqual(self.key(t(17, 7, 5), job="wake_brief"), f"wake_brief:{int(t(17, 7))}")


class NightKey(Base):
    def test_night_key_with_no_wind_down(self):
        self.events([{"event": "wake", "at": t(17, 7)}])
        self.assertEqual(self.night_key(t(17, 21)), "miq:2033-05-17")
        self.assertEqual(self.night_key(t(18, 1)), "miq:2033-05-17")

    def test_night_key_equals_the_event_key_tonight(self):
        self.events([{"event": "wake", "at": t(17, 7)}, {"event": "wind_down", "at": t(17, 22)}])
        self.assertEqual(self.night_key(t(17, 22, 5)), self.key(t(17, 22, 5)))

    def test_night_key_with_no_state(self):
        self.assertEqual(self.night_key(t(17, 21), st=self.root / "nowhere"), "miq:2033-05-17")


if __name__ == "__main__":
    unittest.main()
