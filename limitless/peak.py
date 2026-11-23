"""The post-wake peak: the stretch right after the detected wake event, when the pre-planned task fits now.

    p = post_wake_peak(wake_at, now, peak_h=PEAK_H, blocks=None, long_s=..., gap_s=...)
    # {"open": bool, "in_use": bool, "why": str, "label": str | None}

Open from the wake event (``wake_at``, epoch seconds: a long Sleep-mode on then off, or a screen-event wake;
jobs.wake_times) until ``peak_h`` hours after it. ``peak_h`` is config ``post_wake_peak_h`` (default 2): it
only sets when the card stops saying the words, it is not a target. The cue is the wake event, never a time
of day: nothing here reads the clock or a time of day; ``now`` comes from the caller.

No wake seen is unknown (never guessed), and so is a wake older than window.MAX_AWAKE_H (missing data, not a
long day) or a wake after ``now`` (clock skew).

A focus block (``blocks``: blocks.focus_blocks, ``[(start_s, end_s)]``) that started inside the open peak
uses it once it is still going at ``now`` (its last work row less than ``gap_s`` before ``now``, as in
blocks.current_block) or it lasted ``long_s`` (config ``break_after_min``): then ``in_use`` is True and the
label says "post-wake peak: in use". A short block that already ended does not use it. Block rows that start
after ``now`` are not read; unknown blocks (None) leave the peak open. Unknown and closed have no label: the card says nothing.
``why`` and ``label`` are digit-free T1 words. Pure; stdlib only, Python 3.9+.
"""
from __future__ import annotations

import math
from typing import Optional

from . import blocks as _blocks
from .window import MAX_AWAKE_H

PEAK_H, PEAK_CONFIG = 2.0, "post_wake_peak_h"
OPEN, IN_USE = "post-wake peak: open", "post-wake peak: in use"
LONG_S = _blocks.BREAK_AFTER_MIN * 60.0
NO_WAKE = "unknown: no wake seen"


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def peak_hours(v) -> float:
    """``v`` when it is a positive finite number of hours, else PEAK_H."""
    n = _num(v)
    return n if n is not None and n > 0 else PEAK_H


def _out(is_open: bool, why: str, label: Optional[str] = None, in_use: bool = False) -> dict:
    return {"open": is_open, "in_use": in_use, "why": why, "label": label}


def _used(blocks, wake: float, now: float, long_s: float, gap_s: float) -> bool:
    """True when a block started in [wake, now] and is still going at ``now`` or lasted ``long_s``."""
    for b in blocks or ():
        if not isinstance(b, (tuple, list)) or len(b) != 2:
            continue
        s, e = _num(b[0]), _num(b[1])
        if s is None or e is None or not wake <= s <= now:
            continue
        if now - e < gap_s or min(e, now) - s >= long_s:
            return True
    return False


def post_wake_peak(wake_at, now: float, peak_h=PEAK_H, blocks=None, long_s: float = LONG_S,
                   gap_s: float = _blocks.GAP_S) -> dict:
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
    if _used(blocks, wake, now, long_s, gap_s):
        return _out(True, "in use: a focus block started inside the peak", IN_USE, in_use=True)
    return _out(True, "open since the wake event: the pre-planned task fits now", OPEN)
