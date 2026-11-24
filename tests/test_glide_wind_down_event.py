"""GlideProvider reads Glide's explicit ``wind_down`` event first (docs/glide-wind-down-event.md).

    "wind_down": {"started": epoch_s, "by": "nudge" | "manual", "ended": epoch_s | null}

Open from ``started`` until ``ended`` or WIND_DOWN_MAX_S after ``started``, whichever is first. A
malformed key is ignored (today's ``resume.saved`` path, unchanged); no key is today's behaviour.
A manual wind-down is wind-down but not "Glide already nudged tonight" (the MIQ wind-down line skip).
Synthetic attention.json files only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from limitless import glide_provider as gp  # noqa: E402
from limitless import wind_down  # noqa: E402
import test_wind_down_miq as miq  # noqa: E402

ANCHOR = 1894708800.0  # the wind-down event in every synthetic file
M, H = 60.0, 3600.0
NIGHT = "2030-01-15"
DEFAULT = wind_down.DEFAULT


def resume(saved=ANCHOR):
    return {"saved": saved, "night": NIGHT, "session_id": "s-synthetic", "title": "Synthetic session",
            "last_asks": ["outline the synthetic plan"], "queued": 0}


def attention(event=None, saved=ANCHOR, block=None, **extra):
    """A synthetic attention.json as Glide's wind_down() would leave it, plus the new key when given."""
    data = {"block": block, "queue": [], "resume": resume(saved) if saved is not None else None, "nudged": NIGHT}
    if event is not None:
        data["wind_down"] = event
    data.update(extra)
    return data


def event(started=ANCHOR, by="nudge", ended=None):
    return {"started": started, "by": by, "ended": ended}


class Tmp(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)
        self.n = 0

    def write(self, data):
        self.n += 1
        p = Path(self._d.name) / f"attention-{self.n}.json"
        p.write_text(data if isinstance(data, str) else json.dumps(data))
        return str(p)

    def provider(self, data, now, **kw):
        return gp.GlideProvider(self.write(data), now=now, **kw)

    def state(self, data, now, **kw):
        return self.provider(data, now, **kw).current()


class Open(Tmp):
    def test_open_nudge_is_wind_down(self):
        st = self.state(attention(event()), ANCHOR + 20 * M)
        self.assertEqual((st.cls, st.since, st.source, st.hold_asks), ("wind_down", "wind_down", "glide", False))

    def test_event_is_exposed_with_by(self):
        ev = self.provider(attention(event()), ANCHOR + 20 * M).wind_down_event()
        self.assertEqual(ev, {"started": ANCHOR, "ended": None, "by": "nudge"})

    def test_started_wins_over_a_stale_resume_saved(self):
        # resume.saved alone says history; the event says wind-down opened twenty minutes ago.
        data = attention(event(started=ANCHOR), saved=ANCHOR - 5 * H)
        self.assertEqual(self.state(data, ANCHOR + 20 * M).cls, "wind_down")

    def test_open_without_any_resume(self):
        self.assertEqual(self.state(attention(event(), saved=None), ANCHOR + M).cls, "wind_down")

    def test_opens_at_started_exactly(self):
        self.assertEqual(self.state(attention(event()), ANCHOR).cls, "wind_down")


class Ended(Tmp):
    def test_ended_by_resume_closes_it(self):
        # take_resume() cleared resume next morning and set ended.
        data = attention(event(ended=ANCHOR + 2 * H), saved=None)
        self.assertEqual(self.state(data, ANCHOR + H).cls, "wind_down")
        self.assertEqual(self.state(data, ANCHOR + 2 * H).cls, "unknown")
        self.assertEqual(self.state(data, ANCHOR + 3 * H).cls, "unknown")

    def test_ended_by_block_closes_it_even_with_a_fresh_resume(self):
        # start_block() set ended but leaves resume; the block has since run out.
        blk = {"start": ANCHOR + H, "end": ANCHOR + H + 50 * M, "minutes": 50}
        data = attention(event(ended=ANCHOR + H), block=blk)
        self.assertEqual(self.state(data, ANCHOR + 30 * M).cls, "wind_down")
        self.assertEqual(self.state(data, ANCHOR + H + 10 * M).cls, "peak")
        st = self.state(data, ANCHOR + 2 * H)
        self.assertEqual(st.cls, "unknown")   # today's resume.saved path would say wind_down here
        self.assertEqual(self.provider(data, ANCHOR + 2 * H).wind_down_event()["ended"], ANCHOR + H)

    def test_ended_equal_to_started_is_closed_not_malformed(self):
        data = attention(event(ended=ANCHOR))
        self.assertEqual(self.state(data, ANCHOR + M).cls, "unknown")

    def test_ended_after_now_is_still_open(self):
        self.assertEqual(self.state(attention(event(ended=ANCHOR + 2 * H)), ANCHOR + H).cls, "wind_down")


class Cap(Tmp):
    def test_cap_reached_closes_an_open_event(self):
        data = attention(event(), saved=None)
        self.assertEqual(self.state(data, ANCHOR + gp.WIND_DOWN_MAX_S).cls, "wind_down")
        self.assertEqual(self.state(data, ANCHOR + gp.WIND_DOWN_MAX_S + 1).cls, "unknown")

    def test_cap_wins_over_a_later_ended(self):
        data = attention(event(ended=ANCHOR + gp.WIND_DOWN_MAX_S + 2 * H), saved=None)
        self.assertEqual(self.state(data, ANCHOR + gp.WIND_DOWN_MAX_S + H).cls, "unknown")

    def test_cap_is_a_duration_from_started(self):
        data = attention(event(), saved=None)
        self.assertEqual(self.state(data, ANCHOR + 2 * H, wind_down_max_s=H).cls, "unknown")
        self.assertEqual(self.state(data, ANCHOR + 2 * H, wind_down_max_s=3 * H).cls, "wind_down")

    def test_same_answer_at_every_hour_of_the_day(self):
        for hour in range(24):
            d = hour * H
            data = attention(event(started=ANCHOR + d), saved=None)
            self.assertEqual(self.state(data, ANCHOR + d + M).cls, "wind_down", hour)
            self.assertEqual(self.state(data, ANCHOR + d + gp.WIND_DOWN_MAX_S + 1).cls, "unknown", hour)

    def test_never_reads_the_clock(self):
        with mock.patch("time.time", side_effect=AssertionError("clock read")):
            self.assertEqual(self.state(attention(event()), ANCHOR + M).cls, "wind_down")
            self.assertTrue(wind_down.line({}, attention(event(by="manual")), NIGHT, now=ANCHOR + M))


class By(Tmp):
    def test_manual_is_still_wind_down(self):
        p = self.provider(attention(event(by="manual")), ANCHOR + M)
        self.assertEqual(p.current().cls, "wind_down")
        self.assertEqual(p.wind_down_event()["by"], "manual")

    def test_other_by_values_are_unknown(self):
        for by in ("Nudge", "", None, 3, ["nudge"]):
            ev = event(by=by)
            if by is None:
                del ev["by"]
            p = self.provider(attention(ev), ANCHOR + M)
            self.assertEqual(p.current().cls, "wind_down", by)
            self.assertEqual(p.wind_down_event()["by"], "unknown", by)

    def test_module_function_matches_the_provider(self):
        self.assertEqual(gp.wind_down_event(attention(event(by="manual")), ANCHOR + M),
                         {"started": ANCHOR, "ended": None, "by": "manual"})
        self.assertIsNone(gp.wind_down_event(attention(), ANCHOR + M))
        self.assertIsNone(gp.wind_down_event(attention(event()), None))


class LineSkip(unittest.TestCase):
    """S04: the MIQ wind-down line is skipped only when Glide nudged tonight, not after a manual wind-down."""

    def test_nudge_tonight_skips_the_line(self):
        self.assertEqual(wind_down.line({}, attention(event(by="nudge")), NIGHT, now=ANCHOR + M), "")

    def test_manual_tonight_keeps_the_line(self):
        self.assertEqual(wind_down.line({}, attention(event(by="manual")), NIGHT, now=ANCHOR + M), DEFAULT)
        self.assertFalse(wind_down.glide_nudged(attention(event(by="manual")), NIGHT, now=ANCHOR + M))

    def test_manual_with_no_night_keeps_the_line(self):
        self.assertEqual(wind_down.line({}, attention(event(by="manual")), None, now=ANCHOR + M), DEFAULT)

    def test_unknown_by_counts_as_a_nudge(self):
        self.assertEqual(wind_down.line({}, attention(event(by="later")), NIGHT, now=ANCHOR + M), "")

    def test_manual_on_another_night_is_today_behaviour(self):
        data = attention(event(by="manual"), nudged="2030-01-14")
        self.assertEqual(wind_down.line({}, data, NIGHT, now=ANCHOR + M), DEFAULT)

    def test_without_now_the_key_is_ignored(self):
        # The future-started check needs now; without it the safe side is today's answer.
        self.assertEqual(wind_down.line({}, attention(event(by="manual")), NIGHT), "")

    def test_closed_manual_event_still_is_not_a_nudge(self):
        data = attention(event(by="manual", ended=ANCHOR + H))
        self.assertEqual(wind_down.line({}, data, NIGHT, now=ANCHOR + 2 * H), DEFAULT)

    def test_malformed_key_is_today_behaviour(self):
        for bad in MALFORMED:
            data = attention(bad)
            self.assertEqual(wind_down.line({}, data, NIGHT, now=ANCHOR + M), "", bad)


MALFORMED = (
    "x", [], 3, True,
    {}, {"by": "manual"},
    {"started": "yesterday", "by": "manual", "ended": None},
    {"started": True, "by": "manual", "ended": None},
    {"started": None, "by": "manual", "ended": None},
    {"started": float("inf"), "by": "manual", "ended": None},
    {"started": float("nan"), "by": "manual", "ended": None},
    {"started": ANCHOR + 10 * H, "by": "manual", "ended": None},         # future started
    {"started": ANCHOR, "by": "manual", "ended": ANCHOR - M},            # ended < started
)


class Malformed(Tmp):
    """A malformed key is ignored: the answer is exactly the same file without it."""

    def same_as_without(self, data, now):
        without = {k: v for k, v in data.items() if k != "wind_down"}
        return self.state(data, now), self.state(without, now)

    def test_each_malformed_key_falls_back_to_resume_saved(self):
        for bad in MALFORMED:
            for saved, now in ((ANCHOR, ANCHOR + M), (ANCHOR - 5 * H, ANCHOR + M), (None, ANCHOR + M),
                               (ANCHOR, ANCHOR + gp.WIND_DOWN_MAX_S + 1)):
                got, want = self.same_as_without(attention(bad, saved=saved), now)
                self.assertEqual(got, want, (bad, saved, now))
                self.assertIsNone(self.provider(attention(bad, saved=saved), now).wind_down_event(), bad)

    def test_fresh_resume_with_malformed_key_is_wind_down(self):
        self.assertEqual(self.state(attention({"started": "x"}), ANCHOR + M).cls, "wind_down")

    def test_null_key_is_absent(self):
        got, want = self.same_as_without(attention(saved=ANCHOR, wind_down=None), ANCHOR + M)
        self.assertEqual(got, want)


class Absent(Tmp):
    def test_no_key_is_todays_resume_saved_path(self):
        data = attention()
        self.assertEqual(self.state(data, ANCHOR + 20 * M).cls, "wind_down")
        self.assertEqual(self.state(data, ANCHOR + gp.WIND_DOWN_MAX_S + 1).cls, "unknown")
        self.assertEqual(self.state(data, ANCHOR - M).cls, "unknown")
        self.assertIsNone(self.provider(data, ANCHOR + M).wind_down_event())

    def test_no_key_line_skip_is_todays(self):
        self.assertEqual(wind_down.line({}, attention(), NIGHT, now=ANCHOR + M), "")
        self.assertEqual(wind_down.line({}, attention(nudged=""), NIGHT, now=ANCHOR + M), DEFAULT)

    def test_unreadable_file_has_no_event(self):
        p = gp.GlideProvider(self.write('{"wind_down": '), now=ANCHOR)
        self.assertEqual(p.current().cls, "unknown")
        self.assertIsNone(p.wind_down_event())


class MiqRun(unittest.TestCase):
    """jobs_runner.run_once passes its own now down, so a manual event keeps the line in the one MIQ push."""
    setUp = miq.WindDownRun.setUp
    sleepmode = miq.WindDownRun.sleepmode
    tonight = miq.WindDownRun.tonight
    run_ = miq.WindDownRun.run_
    miq_calls = miq.WindDownRun.miq_calls

    def glide(self, nudged, by=None):
        data = {"block": None, "queue": [], "resume": {"saved": miq.NOW - 120}, "nudged": nudged}
        if by is not None:
            data["wind_down"] = {"started": miq.NOW - 120, "by": by, "ended": None}
        self.att.write_text(json.dumps(data))

    def body(self, by):
        self.glide(self.tonight(), by)
        _, push = self.run_()
        self.assertEqual(self.miq_calls(push), [(miq.MIQ, "send")])          # still one push either way
        return dict(push.sent)[miq.MIQ].splitlines()

    def test_manual_wind_down_keeps_the_line(self):
        self.assertEqual(self.body("manual"), [miq.MIQ_Q, miq.LINE, miq.CHOICES])

    def test_nudge_wind_down_drops_the_line(self):
        self.assertEqual(self.body("nudge"), [miq.MIQ_Q, miq.CHOICES])

    def test_no_key_is_todays_skip(self):
        self.assertEqual(self.body(None), [miq.MIQ_Q, miq.CHOICES])


if __name__ == "__main__":
    unittest.main()
