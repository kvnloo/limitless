"""naps.naps(): Sleep-mode on/off pairs that are a nap, not the night. Synthetic events only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from limitless import naps as N  # noqa: E402

UTC = timezone.utc
H = 3600.0


def at(day, hh, mm=0):
    """Epoch seconds of a synthetic UTC time on day ``day`` of an arbitrary month."""
    return datetime(2030, 3, day, hh, mm, tzinfo=UTC).timestamp()


def on(t):
    return {"event": "sleep_mode_on", "at": t}


def off(t):
    return {"event": "sleep_mode_off", "at": t}


def night(day_from, h_from, day_to, h_to):
    return [on(at(day_from, h_from)), off(at(day_to, h_to))]


DAY = (at(11, 0), at(12, 0))      # the local day under test (UTC here)


class Naps(unittest.TestCase):
    def test_a_short_daytime_pair_is_a_nap(self):
        evs = night(10, 23, 11, 7) + [on(at(11, 14)), off(at(11, 14, 40))] + night(11, 23, 12, 7)
        self.assertEqual(N.naps(evs, *DAY, tz=UTC), [{"start_s": at(11, 14), "end_s": at(11, 14, 40)}])

    def test_the_night_is_never_a_nap(self):
        evs = night(10, 23, 11, 7) + night(11, 23, 12, 7)
        self.assertEqual(N.naps(evs, *DAY, tz=UTC), [])

    def test_a_pair_as_long_as_nap_max_is_not_a_nap(self):
        evs = night(10, 23, 11, 7) + [on(at(11, 13)), off(at(11, 15))]
        self.assertEqual(N.naps(evs, *DAY, tz=UTC), [])
        self.assertEqual(len(N.naps(evs, *DAY, nap_max_h=3, tz=UTC)), 1)

    def test_a_short_night_alone_in_its_day_is_not_a_nap(self):
        evs = [on(at(11, 3)), off(at(11, 4, 30))]       # the only sleep that ended this day: the night
        self.assertEqual(N.naps(evs, *DAY, tz=UTC), [])

    def test_a_nap_before_a_night_that_starts_after_midnight_still_counts(self):
        evs = night(10, 23, 11, 7) + [on(at(11, 15)), off(at(11, 15, 30))] + night(12, 1, 12, 8)
        self.assertEqual(len(N.naps(evs, *DAY, tz=UTC)), 1)

    def test_an_on_with_no_off_is_open_not_a_nap(self):
        evs = night(10, 23, 11, 7) + [on(at(11, 14))]
        self.assertEqual(N.naps(evs, *DAY, tz=UTC), [])

    def test_two_naps_oldest_first(self):
        evs = night(10, 23, 11, 7) + [on(at(11, 16)), off(at(11, 16, 20)), on(at(11, 12)), off(at(11, 12, 30))]
        got = N.naps(evs, *DAY, tz=UTC)
        self.assertEqual([n["start_s"] for n in got], [at(11, 12), at(11, 16)])

    def test_no_sleep_mode_event_in_range_is_unknown_not_zero(self):
        self.assertIsNone(N.naps([], *DAY, tz=UTC))
        self.assertIsNone(N.naps(night(8, 23, 9, 7), *DAY, tz=UTC))
        self.assertIsNone(N.naps([{"event": "wake", "at": at(11, 7)}], *DAY, tz=UTC))

    def test_bad_input_never_raises(self):
        self.assertIsNone(N.naps(None, *DAY, tz=UTC))
        self.assertIsNone(N.naps([None, {"event": "sleep_mode_on", "at": "nope"}, 5], *DAY, tz=UTC))
        self.assertIsNone(N.naps([on(at(11, 9))], "x", None, tz=UTC))

    def test_iso_times_are_read(self):
        evs = [{"event": "sleep_mode_on", "at": "2030-03-10T23:00:00Z"},
               {"event": "sleep_mode_off", "at": "2030-03-11T07:00:00Z"},
               {"event": "sleep_mode_on", "at": "2030-03-11T14:00:00Z"},
               {"event": "sleep_mode_off", "at": "2030-03-11T14:30:00Z"}]
        self.assertEqual(len(N.naps(evs, *DAY, tz=UTC)), 1)


class NapMax(unittest.TestCase):
    def test_config_nap_max_h_default_two(self):
        self.assertEqual(N.NAP_MAX_H, 2.0)
        self.assertEqual(N.nap_max_h({}), 2.0)
        self.assertEqual(N.nap_max_h({"nap_max_h": 1.5}), 1.5)
        for bad in (0, -1, True, "2", 30, None):
            self.assertEqual(N.nap_max_h({"nap_max_h": bad}), 2.0, bad)


if __name__ == "__main__":
    unittest.main()
