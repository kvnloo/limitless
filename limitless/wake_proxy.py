"""A fallback wake event from Android screen events, for days the person does not use Sleep mode.

Input: screen-events.jsonl rows ``{"ts": epoch_ms, "type": str, "pkg": str}``. Only the person's own
actions count: an unlock (KEYGUARD_HIDDEN) or a touch (USER_INTERACTION). A notification row, or a
screen that lights up and goes dark again, is the phone, not the person.

A wake is the first such action after a person-quiet gap of at least ``min_gap_s``. The gap is a
duration measured from the person's last action; nothing here reads or compares a time of day.
A short night has no such gap: then the longest quiet gap of at least ``SHORT_NIGHT_MIN_S`` whose
24 h span holds no other wake is a wake too, marked ``"short": true`` with a lower confidence.
The gap is a quiet phone, not sleep: no event carries a sleep duration.
Each event says ``"source": "screen"`` and carries a confidence below the Sleep-mode one
(jobs.SLEEP_MODE_CONFIDENCE), so a Sleep-mode wake wins when both describe the same gap
(jobs.merged_events). Pure functions; stdlib only, Python 3.9+.
"""
from __future__ import annotations

from typing import Optional

PERSON = ("KEYGUARD_HIDDEN", "USER_INTERACTION")   # the person's own actions; everything else is ignored
MIN_GAP_S = 4 * 3600        # a quiet gap at least this long, then an action, is a wake (longer than a nap)
SCREEN_CONFIDENCE = 0.6     # below jobs.SLEEP_MODE_CONFIDENCE: a quiet phone is weaker evidence of sleep
SHORT_NIGHT_MIN_S = 3 * 3600   # a short-night fallback wake needs at least this quiet gap
SHORT_CONFIDENCE = 0.4      # below SCREEN_CONFIDENCE: the longest gap of a day is weaker evidence still
SAME_DAY_S = MIN_GAP_S + 20 * 3600   # two quiet gaps that fit in one span this long belong to one day


MS_ABOVE = 1e11             # an epoch above this is milliseconds (1e11 s is far in the future); else seconds


def _ts_s(row) -> Optional[float]:
    """Epoch seconds of a row's ``ts``, which some exporters write in seconds and others in milliseconds."""
    v = row.get("ts") if isinstance(row, dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) / 1000.0 if v > MS_ABOVE else float(v)


def person_times(rows: list) -> list:
    """Sorted epoch seconds of the person's own actions (unlocks and touches) in screen-event rows."""
    out = []
    for r in rows or ():
        t = _ts_s(r)
        if t is not None and r.get("type") in PERSON:
            out.append(t)
    return sorted(out)


def _same_day(a: tuple, b: tuple, span_s: float) -> bool:
    """True when quiet gaps ``a`` and ``b`` ((from, to) seconds) both fit inside one ``span_s`` span."""
    return max(a[1], b[1]) - min(a[0], b[0]) < span_s


def events_from_screen(rows: list, *, min_gap_s: float = MIN_GAP_S,
                       short_min_s: float = SHORT_NIGHT_MIN_S) -> list:
    """Wake events ``{"event": "wake", "at", "gap_from", "source": "screen", "confidence"}``, oldest first.

    ``gap_from`` is the person's last action before the quiet gap. The first action in the rows has
    no known gap before it, so it is never a wake. Every gap of at least ``min_gap_s`` is a wake.
    Then, longest first, a gap of at least ``short_min_s`` (and under ``min_gap_s``) is a short wake
    (``"short": True``, SHORT_CONFIDENCE) unless it and another wake's gap fit in one SAME_DAY_S span:
    one wake per day, and a long break on a normal day is never a second one. Durations only.
    """
    times = person_times(rows)
    out, taken, short = [], [], []
    for prev, cur in zip(times, times[1:]):
        if cur - prev >= min_gap_s:
            out.append({"event": "wake", "at": cur, "gap_from": prev, "source": "screen",
                        "confidence": SCREEN_CONFIDENCE})
            taken.append((prev, cur))
        elif cur - prev >= short_min_s:
            short.append((prev, cur))
    for gap in sorted(short, key=lambda g: (g[0] - g[1], g[1])):     # longest first; ties: the earlier
        if not any(_same_day(gap, t, SAME_DAY_S) for t in taken):
            out.append({"event": "wake", "at": gap[1], "gap_from": gap[0], "source": "screen",
                        "confidence": SHORT_CONFIDENCE, "short": True})
            taken.append(gap)
    return sorted(out, key=lambda e: e["at"])
