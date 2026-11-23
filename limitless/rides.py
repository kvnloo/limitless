"""Bike rides, weekly and in words only: did rides happen this week, and more or fewer than last week?

    w = week(rows, today)
    # {"this_week": int|None, "last_week": int|None, "minutes_this_week": int|None,
    #  "minutes_last_week": int|None, "count": word|None, "compare": word|None, "label": T1 dict}

Rows are StateReader.ride_rows(): one per exercise session of a ride kind, ``{"start", "duration_s", "kind",
"source"}``. This week is ``today`` and the six days before it; last week is the seven days before that. A
ride's day is the date of its start in the start's own offset (the person's local day when it was logged).

Words: "rides this week: none | one | two | a few", then "same as last week | more than last week | fewer
than last week". ``rows`` that is not a list (no rides file) is unknown: no count, label "unknown" and no
review line. An empty list is a known week with no ride: "none", never "missed".

Tiers: counts and minutes are T0 and stay in code; ``label`` and ``review_line`` are T1 words with no digit.
No target, no score, no streak, no advice. Nothing here reads the clock, touches a file or sends.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Optional

WEEK_DAYS = 7
MODALITY = "measured"
UNKNOWN = "unknown"
COUNTS = ("none", "one", "two", "a few")
COMPARES = ("same as last week", "more than last week", "fewer than last week")
LABELS = (UNKNOWN,) + tuple(f"rides this week: {c}, {k}" for c in COUNTS for k in COMPARES)


def count_word(n: int) -> str:
    return COUNTS[min(max(n, 0), len(COUNTS) - 1)]


def _day(r) -> Optional[date]:
    """The local date of a ride's start (its own offset), or None for a row that is not a ride."""
    if not isinstance(r, dict) or not isinstance(r.get("start"), str):
        return None
    try:
        dt = datetime.fromisoformat(r["start"].replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.date() if dt.tzinfo is not None and dt.utcoffset() is not None else None


def _seconds(r) -> Optional[float]:
    v = r.get("duration_s")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
        return None
    return float(v)


def _t1(word: str) -> dict:
    return {"label": word, "tier": "T1", "modality": MODALITY}


def week(rows, today: date) -> dict:
    """Rides in this week and last week up to ``today``; never raises (bad input reads as unknown)."""
    out = {"this_week": None, "last_week": None, "minutes_this_week": None, "minutes_last_week": None,
           "count": None, "compare": None, "label": _t1(UNKNOWN)}
    if not isinstance(rows, (list, tuple)) or not isinstance(today, date):
        return out
    this_first = today - timedelta(days=WEEK_DAYS - 1)
    last_first = this_first - timedelta(days=WEEK_DAYS)
    n = {"this": 0, "last": 0}
    secs = {"this": 0.0, "last": 0.0}
    for r in rows:
        d = _day(r)
        s = _seconds(r) if d is not None else None
        if s is None or d > today or d < last_first:
            continue
        side = "this" if d >= this_first else "last"
        n[side] += 1
        secs[side] += s
    count = count_word(n["this"])
    compare = COMPARES[0] if n["this"] == n["last"] else COMPARES[1] if n["this"] > n["last"] else COMPARES[2]
    out.update(this_week=n["this"], last_week=n["last"], minutes_this_week=int(round(secs["this"] / 60)),
               minutes_last_week=int(round(secs["last"] / 60)), count=count, compare=compare,
               label=_t1(f"rides this week: {count}, {compare}"))
    return out


def review_line(w: Optional[dict]) -> str:
    """The week review's rides line, digit-free; "" when the week is unknown (no rides file)."""
    lab = w.get("label") if isinstance(w, dict) else None
    word = lab.get("label") if isinstance(lab, dict) else None
    if not isinstance(word, str) or word not in LABELS or word == UNKNOWN:
        return ""
    return f"{word[0].upper()}{word[1:]}."
