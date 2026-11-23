"""The post-wake peak: the stretch right after the detected wake event, when the pre-planned task fits now.

    p = post_wake_peak(wake_at, now, peak_h=PEAK_H)   # {"open": bool, "why": str, "label": str | None}

Open from the wake event (``wake_at``, epoch seconds: a long Sleep-mode on then off, or a screen-event wake;
jobs.wake_times) until ``peak_h`` hours after it. ``peak_h`` is config ``post_wake_peak_h`` (default 2): it
only sets when the card stops saying the words, it is not a target. The cue is the wake event, never a time
of day: nothing here reads the clock or a time of day; ``now`` comes from the caller.

No wake seen is unknown (never guessed), and so is a wake older than window.MAX_AWAKE_H (missing data, not a
long day) or a wake after ``now`` (clock skew). Unknown and closed have no label: the card says nothing.
``why`` and ``label`` are digit-free T1 words. Pure; stdlib only, Python 3.9+.
"""
from __future__ import annotations

import math
from typing import Optional

from .window import MAX_AWAKE_H

PEAK_H, PEAK_CONFIG = 2.0, "post_wake_peak_h"
OPEN = "post-wake peak: open"
NO_WAKE = "unknown: no wake seen"


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def peak_hours(v) -> float:
    """``v`` when it is a positive finite number of hours, else PEAK_H."""
    n = _num(v)
    return n if n is not None and n > 0 else PEAK_H


def _out(is_open: bool, why: str, label: Optional[str] = None) -> dict:
    return {"open": is_open, "why": why, "label": label}


def post_wake_peak(wake_at, now: float, peak_h=PEAK_H) -> dict:
    """``{"open", "why", "label"}`` for the post-wake peak at ``now``; see the module doc."""
    wake, now = _num(wake_at), float(now)
    if wake is None:
        return _out(False, NO_WAKE)
    since_s = now - wake
    if since_s < 0:
        return _out(False, "unknown: the wake event is after now")
    if since_s > MAX_AWAKE_H * 3600:
        return _out(False, "unknown: the last wake event is too old")
    if since_s >= peak_hours(peak_h) * 3600:
        return _out(False, "closed: the peak after the wake event has passed")
    return _out(True, "open since the wake event: the pre-planned task fits now", OPEN)
