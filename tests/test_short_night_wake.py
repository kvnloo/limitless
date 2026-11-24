"""A short night still yields one wake: the first quiet gap of a day with no >= MIN_GAP_S gap.

Synthetic rows only. T0 is an arbitrary epoch; only differences between times matter.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card, jobs, jobs_runner, wake_proxy  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

T0 = 2_000_000_000.0
H = 3600.0
KEYS = {"event", "at", "gap_from", "source", "confidence", "short"}


def touch(at_h):
    return {"ts": int((T0 + at_h * H) * 1000), "type": "USER_INTERACTION", "pkg": "com.example.app"}


def day(start_h, quiet_h, quiet_at_h, end_h, step_h=2.0, extra=()):
    """Touches every ``step_h`` from ``start_h`` to ``end_h``, with one quiet gap of ``quiet_h``
    starting at ``quiet_at_h`` (no touches inside it), plus quiet gaps in ``extra`` ((at_h, len_h), ...)."""
    gaps = [(quiet_at_h, quiet_h)] + list(extra)
    marks = {start_h, end_h}
    for a, n in gaps:
        marks |= {a, a + n}
    t = start_h
    while t <= end_h:
        marks.add(t)
        t += step_h
    keep = sorted(m for m in marks if not any(a < m < a + n for a, n in gaps))
    return [touch(m) for m in keep]


class ShortNight(unittest.TestCase):
    def test_a_only_long_gap_is_3_5_h_gives_one_short_wake_at_its_end(self):
        rows = day(0, 3.5, 2.0, 24)                 # quiet 2.0 -> 5.5; every other gap is 2 h or less
        evs = wake_proxy.events_from_screen(rows)
        self.assertEqual(len(evs), 1, evs)
        e = evs[0]
        self.assertEqual(e["at"], T0 + 5.5 * H)
        self.assertEqual(e["gap_from"], T0 + 2.0 * H)
        self.assertIs(e["short"], True)
        self.assertEqual(e["source"], "screen")
        self.assertLess(e["confidence"], wake_proxy.SCREEN_CONFIDENCE)
        self.assertGreater(e["confidence"], 0)
        self.assertEqual(set(e), KEYS)              # no sleep duration is claimed

    def test_b_normal_night_and_a_daytime_break_give_only_the_night_wake(self):
        rows = day(0, 5.0, 1.0, 24, extra=[(13.0, 3.2)])
        evs = wake_proxy.events_from_screen(rows)
        self.assertEqual([e["at"] for e in evs], [T0 + 6.0 * H])
        self.assertNotIn("short", evs[0])
        self.assertEqual(evs[0]["confidence"], wake_proxy.SCREEN_CONFIDENCE)

    def test_b_the_break_before_the_night_is_not_a_wake_either(self):
        # With last night's wake in the rows, the break shares its day and is not a wake.
        rows = day(-8, 6.0, -6.0, 30, extra=[(9.0, 3.2), (18.0, 5.0)])  # night -6 -> 0, break 9.0 -> 12.2, night 18 -> 23
        self.assertEqual([e["at"] for e in wake_proxy.events_from_screen(rows)], [T0 + 0.0 * H, T0 + 23.0 * H])

    def test_b_a_break_seen_as_a_short_wake_stays_one_after_the_night(self):
        # Prefix stability: with no earlier wake in the rows, the poll at 12.2 h sees the break as a short
        # wake. The night that ends later does not take it back; the night is its own (long) wake.
        rows = day(0, 3.2, 9.0, 30, extra=[(18.0, 5.0)])  # break 9.0 -> 12.2, then night 18 -> 23
        evs = wake_proxy.events_from_screen(rows)
        self.assertEqual([(e["at"], e.get("short", False)) for e in evs], [(T0 + 12.2 * H, True), (T0 + 23.0 * H, False)])

    def test_c_only_gaps_under_3_h_give_no_wake(self):
        rows = day(0, 2.9, 3.0, 48, step_h=2.5)
        self.assertEqual(wake_proxy.events_from_screen(rows), [])

    def test_d_two_short_night_days_give_one_short_wake_each(self):
        rows = day(0, 3.5, 2.0, 48, extra=[(26.0, 3.4)])
        evs = wake_proxy.events_from_screen(rows)
        self.assertEqual([e["at"] for e in evs], [T0 + 5.5 * H, T0 + 29.4 * H])
        self.assertTrue(all(e["short"] for e in evs))

    def test_d_two_short_nights_a_little_less_than_a_day_apart(self):
        # The second night ends 23 h after the first: still its own day (both gaps span 26.5 h).
        rows = day(0, 3.5, 2.0, 48, extra=[(25.0, 3.5)])
        self.assertEqual([e["at"] for e in wake_proxy.events_from_screen(rows)], [T0 + 5.5 * H, T0 + 28.5 * H])

    def test_the_first_gap_of_the_day_wins(self):
        # Was "the longest gap wins" (15.6 h). The first poll after 5.2 h already saw that wake;
        # a longer gap later the same day must not move it.
        rows = day(0, 3.2, 2.0, 24, extra=[(12.0, 3.6)])
        evs = wake_proxy.events_from_screen(rows)
        self.assertEqual([e["at"] for e in evs], [T0 + 5.2 * H])

    def test_no_short_wake_near_a_long_wake(self):
        # A normal night, then long breaks over the next 20 h: none of them is a second wake.
        rows = day(0, 6.0, 0.0, 26, extra=[(10.0, 3.5), (19.0, 3.9)])
        self.assertEqual([e["at"] for e in wake_proxy.events_from_screen(rows)], [T0 + 6.0 * H])

    def test_short_wake_is_a_duration_rule(self):
        base = day(0, 3.5, 2.0, 24)
        for shift_h in (0, 3.25, 7.5, 13, 19.75):
            rows = [dict(r, ts=r["ts"] + int(shift_h * H * 1000)) for r in base]
            self.assertEqual([e["at"] for e in wake_proxy.events_from_screen(rows)], [T0 + (5.5 + shift_h) * H])

    def test_threshold_constants(self):
        self.assertEqual(wake_proxy.SHORT_NIGHT_MIN_S, 3 * H)
        self.assertLess(wake_proxy.SHORT_NIGHT_MIN_S, wake_proxy.MIN_GAP_S)
        self.assertLess(wake_proxy.SHORT_CONFIDENCE, wake_proxy.SCREEN_CONFIDENCE)


class RunnerShortNight(unittest.TestCase):
    NOW = T0 + 6.0 * H

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json")}
        rows = day(-20, 3.5, 2.0, 5.9)               # quiet 2.0 -> 5.5, NOW is half an hour later
        (self.st / "screen-events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def tearDown(self):
        self.tmp.cleanup()

    def _rows(self):
        return {r["job"]: r for r in jobs_runner.run_once(self.st, self.NOW, env=self.env, home=self.root)}

    def test_e_short_night_triggers_the_wake_brief(self):
        row = self._rows()["Wake-up brief"]
        self.assertNotEqual(row["action"], jobs.NOT_TRIGGERED, row)

    def test_the_verdict_labels_the_wake_as_a_proxy(self):
        self.assertIn("(proxy)", self._rows()["Wake-up brief"]["reason"])

    def test_dry_run_writes_nothing(self):
        before = sorted(p.name for p in self.st.iterdir())
        self._rows()
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), before)

    def test_brief_text_claims_no_sleep_duration(self):
        text = jobs_runner.body(jobs.WAKE_BRIEF)
        self.assertIsNone(re.search(r"\d|(?i:slept|sleep)", text), text)

    def test_card_claims_no_sleep_from_the_screen_wake(self):
        c = card.build(StateReader(self.st), self.NOW, date(2033, 5, 18))
        self.assertIsNone(c["items"]["sleep"]["value"])
        self.assertIn("sleep unknown", c["text"])


if __name__ == "__main__":
    unittest.main()
