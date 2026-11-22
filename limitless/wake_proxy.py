"""A fallback wake event from Android screen events, for days the person does not use Sleep mode.

Input: screen-events.jsonl rows ``{"ts": epoch_ms, "type": str, "pkg": str}``. Only the person's own
actions count: an unlock (KEYGUARD_HIDDEN) or a touch (USER_INTERACTION). A notification row, or a
screen that lights up and goes dark again, is the phone, not the person.

A wake is the first such action after a person-quiet gap of at least ``min_gap_s``. The gap is a
duration measured from the person's last action; nothing here reads or compares a time of day.
Each event says ``"source": "screen"`` and carries a confidence below the Sleep-mode one
(jobs.SLEEP_MODE_CONFIDENCE), so a Sleep-mode wake wins when both describe the same gap
(jobs.merged_events). Pure functions; stdlib only, Python 3.9+.
"""
from __future__ import annotations

from typing import Optional

PERSON = ("KEYGUARD_HIDDEN", "USER_INTERACTION")   # the person's own actions; everything else is ignored
MIN_GAP_S = 4 * 3600        # a quiet gap at least this long, then an action, is a wake (longer than a nap)
SCREEN_CONFIDENCE = 0.6     # below jobs.SLEEP_MODE_CONFIDENCE: a quiet phone is weaker evidence of sleep


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


def events_from_screen(rows: list, *, min_gap_s: float = MIN_GAP_S) -> list:
    """Wake events ``{"event": "wake", "at", "gap_from", "source": "screen", "confidence"}``, oldest first.

    ``gap_from`` is the person's last action before the quiet gap. The first action in the rows has
    no known gap before it, so it is never a wake.
    """
    times = person_times(rows)
    out = []
    for prev, cur in zip(times, times[1:]):
        if cur - prev >= min_gap_s:
            out.append({"event": "wake", "at": cur, "gap_from": prev, "source": "screen",
                        "confidence": SCREEN_CONFIDENCE})
    return out
