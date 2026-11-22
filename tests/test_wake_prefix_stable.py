"""A wake, once seen, never moves: the screen wakes of the rows seen so far are kept by every later poll.

Property (durations only, no time-of-day rule): for rows R and any cut time c, every wake that
``events_from_screen(rows with ts <= c)`` emits is also emitted, with the same ``at`` and ``gap_from``,
by ``events_from_screen(R)``. Synthetic rows only; T0 is an arbitrary epoch.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, jobs_runner, wake_proxy  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

T0 = 2_000_000_000.0
H = 3600.0


def touch(at_h, kind="USER_INTERACTION"):
    return {"ts": int((T0 + at_h * H) * 1000), "type": kind, "pkg": "com.example.app"}


def day(start_h, end_h, gaps, step_h=2.0):
    """Touches every ``step_h`` from ``start_h`` to ``end_h`` except inside the quiet ``gaps`` ((at_h, len_h), ...),
    plus a notification row inside each gap (the phone, not the person)."""
    marks = {start_h, end_h}
    for a, n in gaps:
        marks |= {a, a + n}
    t = start_h
    while t <= end_h:
        marks.add(t)
        t += step_h
    keep = sorted(m for m in marks if not any(a < m < a + n for a, n in gaps))
    return [touch(m) for m in keep] + [touch(a + n / 2, "NOTIFICATION_INTERRUPTION") for a, n in gaps]


DAYS = {
    "one short night": day(0, 24, [(2.0, 3.5)]),
    "a short night, then a longer daytime break": day(0, 24, [(2.0, 3.2), (12.0, 3.6)]),
    "a short night, then two longer breaks": day(0, 30, [(2.0, 3.1), (9.0, 3.4), (17.0, 3.9)]),
    "two short nights a day apart": day(0, 48, [(2.0, 3.5), (26.0, 3.4)]),
    "two short nights a little less than a day apart": day(0, 48, [(2.0, 3.5), (25.0, 3.5)]),
    "a normal night and a daytime break": day(0, 24, [(1.0, 5.0), (13.0, 3.2)]),
    "a normal night and long breaks": day(0, 26, [(0.0, 6.0), (10.0, 3.5), (19.0, 3.9)]),
    "a daytime break, then a normal night": day(0, 30, [(9.0, 3.2), (18.0, 5.0)]),
    "a short night, then a normal night": day(0, 48, [(2.0, 3.5), (22.0, 6.0)]),
}


def _wake(e):
    return (e["at"], e["gap_from"], e.get("short", False))


def _cuts(rows):
    return sorted({wake_proxy._ts_s(r) for r in rows})


def _upto(rows, c):
    return [r for r in rows if wake_proxy._ts_s(r) <= c]


class PrefixStable(unittest.TestCase):
    def test_every_wake_seen_at_a_cut_is_kept_by_the_full_rows(self):
        for name, rows in DAYS.items():
            full = {_wake(e) for e in wake_proxy.events_from_screen(rows)}
            for c in _cuts(rows):
                for e in wake_proxy.events_from_screen(_upto(rows, c)):
                    with self.subTest(day=name, cut_h=(c - T0) / H, at_h=(e["at"] - T0) / H):
                        self.assertIn(_wake(e), full)

    def test_every_wake_seen_at_a_cut_is_kept_by_every_later_cut(self):
        for name, rows in DAYS.items():
            cuts = _cuts(rows)
            outs = [{_wake(e) for e in wake_proxy.events_from_screen(_upto(rows, c))} for c in cuts]
            for i in range(len(outs) - 1):
                with self.subTest(day=name, cut_h=(cuts[i] - T0) / H):
                    self.assertLessEqual(outs[i], outs[i + 1])

    def test_no_short_wake_shares_a_day_with_an_earlier_wake(self):
        # At most one short wake per day, and none after a long wake of the same day. A long wake after a
        # short one stays: the short one was already seen, and a long gap is always a wake.
        for name, rows in DAYS.items():
            evs = wake_proxy.events_from_screen(rows)
            for i, a in enumerate(evs):
                for b in evs[i + 1:]:
                    if b.get("short"):
                        with self.subTest(day=name, a_h=(a["at"] - T0) / H, b_h=(b["at"] - T0) / H):
                            self.assertFalse(wake_proxy._same_day((a["gap_from"], a["at"]),
                                                                  (b["gap_from"], b["at"]), wake_proxy.SAME_DAY_S))

    def test_the_first_short_gap_of_a_day_wins(self):
        evs = wake_proxy.events_from_screen(DAYS["a short night, then a longer daytime break"])
        self.assertEqual([(e["gap_from"], e["at"]) for e in evs], [(T0 + 2.0 * H, T0 + 5.2 * H)])
        self.assertIs(evs[0]["short"], True)

    def test_a_long_wake_is_never_dropped_for_an_earlier_short_one(self):
        evs = wake_proxy.events_from_screen(DAYS["a short night, then a normal night"])
        self.assertEqual([(e["at"], e.get("short", False)) for e in evs],
                         [(T0 + 5.5 * H, True), (T0 + 28.0 * H, False)])
        self.assertEqual(evs[1]["confidence"], wake_proxy.SCREEN_CONFIDENCE)

    def test_a_normal_night_and_long_breaks_give_one_wake(self):
        for name in ("a normal night and a daytime break", "a normal night and long breaks"):
            evs = wake_proxy.events_from_screen(DAYS[name])
            self.assertEqual(len(evs), 1, (name, evs))
            self.assertNotIn("short", evs[0])


class RunnerPollsOneDay(unittest.TestCase):
    """The runner polls every 15 min on the rows seen so far: a short night 2.0 -> 5.2 h, then a longer
    daytime break 12.0 -> 15.6 h. The Wake-up brief is about one fixed wake and is spoken once."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json")}
        self.rows = day(-20, 20, [(2.0, 3.2), (12.0, 3.6)], step_h=0.5)

    def tearDown(self):
        self.tmp.cleanup()

    def _poll(self, now):
        seen = [r for r in self.rows if wake_proxy._ts_s(r) <= now]
        (self.st / "screen-events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in seen))
        row = {r["job"]: r for r in jobs_runner.run_once(self.st, now, env=self.env, home=self.root)}["Wake-up brief"]
        # run_once's own inputs, to read the trigger time its verdict is about
        sent = StateReader(self.st).jobs_sent()
        v = jobs.should_fire(jobs.WAKE_BRIEF, jobs_runner.events(StateReader(self.st), env=self.env, home=self.root),
                             None, sent, now)
        return row, v.trigger_at

    def test_the_wake_brief_trigger_never_changes_and_it_speaks_once(self):
        first, delivered = None, []
        for i in range(int(4 / 0.25), int(19 / 0.25) + 1):
            now = T0 + i * 0.25 * H
            row, trig = self._poll(now)
            if row["action"] == jobs.DELIVER:
                delivered.append(i * 0.25)
                # what a real delivery appends; run_once itself stays a dry run and writes nothing
                with open(self.st / jobs_runner.SENT_LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps(jobs.sent_entry(jobs.WAKE_BRIEF, trig, now)) + "\n")
            if first is None and trig is not None:
                first = trig
            with self.subTest(now_h=i * 0.25):
                if first is not None:
                    self.assertEqual(trig, first, row)
        self.assertEqual(first, T0 + 5.2 * H)
        self.assertEqual(len(delivered), 1, delivered)


if __name__ == "__main__":
    unittest.main()
