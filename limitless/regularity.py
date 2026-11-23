"""Sleep regularity, in words only: how steady sleep times have been, per source, never a target time.

    r = regularity(nights, min_nights=MIN_NIGHTS, tz=None)
    # {"wearable": kind, "proxy": kind}; kind = {"known", "nights", "mid_spread_min", "wake_spread_min",
    #                                           "drift_min", "drift", "pattern"}
    lab = label(r)      # T1 dict: "wearable: sleep times steady" / "phone estimate: drifting later" / "unknown: ..."
    clause(r)           # the week review's clause: "wearable says sleep times steady"; "" when unknown

Input is sleep.timed_nights(): ``{"night": "YYYY-MM-DD", "wearable": (start_s, end_s) | None,
"proxy": (start_s, end_s) | None}`` oldest first. Only the last MAX_NIGHTS nights count. Each source is read on
its own, never mixed: a wearable night and a phone night are different measures. A source with fewer than
``min_nights`` spans (config ``regularity_min_nights``, default MIN_NIGHTS) is unknown, never "regular".

Per source: the midpoint and the end (wake) of each span as a local minute of the day, on a circle, so a night
either side of midnight is minutes apart, not a day. The spread is the circular standard deviation in minutes.
Drift is the least-squares slope of the midpoints (unwrapped around their circular mean) against the night's
date, times the nights covered, in minutes (+ later, - earlier): ``drift`` is "later" or "earlier" at
DRIFT_MIN or more, else "steady". ``pattern``: "later" / "earlier" when the drift is that large and the nights
sit close to the drift line (residual spread at most STEADY_SPREAD_MIN), else "varies" when the midpoint or
wake spread is over STEADY_SPREAD_MIN, else "steady".

Words (T1, no digit, no clock time): the wearable's when it is known, else the phone estimate's, always with
the source named: "wearable: sleep times steady | sleep times vary a lot | drifting later | drifting earlier"
(or "phone estimate: ..."), else "unknown: too few nights ..." / "unknown: no nights ...".

Tiers: minutes and counts are T0 and stay in code (the tool shows them only under the raw opt-in); ``label`` and
``clause`` are T1 words. Observation only: no target, no bedtime, no advice.
Nothing here reads the clock, touches a file or sends. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import math
from datetime import date, datetime, tzinfo
from typing import Mapping, Optional

MIN_NIGHTS = 4               # fewer spans than this from one source: unknown
MAX_NIGHTS = 14              # only the last two weeks of nights count
STEADY_SPREAD_MIN = 60.0     # a circular spread (midpoint or wake) above this varies a lot
DRIFT_MIN = 60.0             # a drift across the window of at least this is drifting later / earlier
MAX_SPAN_S = 24 * 3600       # a span this long or longer is a hole in the data, not a night
CONFIG_KEY = "regularity_min_nights"
DAY_MIN = 1440.0
SOURCES = ("wearable", "proxy")            # the wearable is read first; the phone estimate stands in for it
NAMES = {"wearable": "wearable", "proxy": "phone estimate"}
MODALITY = {"wearable": "measured", "proxy": "proxy"}
WORDS = {"steady": "sleep times steady", "varies": "sleep times vary a lot", "later": "drifting later",
         "earlier": "drifting earlier"}
UNKNOWN_FEW = "unknown: too few nights with sleep times from the wearable or the phone estimate"
UNKNOWN_NONE = "unknown: no nights with sleep times from the wearable or the phone estimate"
LABELS = tuple(f"{NAMES[s]}: {w}" for s in SOURCES for w in WORDS.values()) + (UNKNOWN_FEW, UNKNOWN_NONE)
CLAUSES = tuple(f"{NAMES[s]} says {w}" for s in SOURCES for w in WORDS.values())


def min_nights(cfg: Optional[Mapping]) -> int:
    """Config ``regularity_min_nights`` when it is an int of at least two, else MIN_NIGHTS."""
    v = cfg.get(CONFIG_KEY) if isinstance(cfg, Mapping) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 2 else MIN_NIGHTS


def _span(v) -> Optional[tuple]:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        return None
    a, b = v
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (a, b)):
        return None
    return (float(a), float(b)) if 0 < b - a < MAX_SPAN_S else None


def _day(night) -> Optional[int]:
    try:
        return date.fromisoformat(night).toordinal() if isinstance(night, str) else None
    except ValueError:
        return None


def _minute(t: float, tz: Optional[tzinfo]) -> Optional[float]:
    try:
        dt = datetime.fromtimestamp(t, tz)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.hour * 60 + dt.minute + dt.second / 60 + dt.microsecond / 6e7


def _circ(mins: list) -> tuple:
    """(circular mean minute, circular standard deviation in minutes) of minutes of the day."""
    k = 2 * math.pi / DAY_MIN
    c = sum(math.cos(m * k) for m in mins) / len(mins)
    s = sum(math.sin(m * k) for m in mins) / len(mins)
    r = min(1.0, math.hypot(c, s))
    mean = (math.atan2(s, c) / k) % DAY_MIN
    sd = math.sqrt(-2 * math.log(r)) / k if r > 1e-12 else DAY_MIN / 2
    return mean, sd


def _signed(m: float, mean: float) -> float:
    """``m - mean`` on the circle, in (-720, 720]."""
    d = (m - mean) % DAY_MIN
    return d - DAY_MIN if d > DAY_MIN / 2 else d


def _unknown(n: int) -> dict:
    return {"known": False, "nights": n, "mid_spread_min": None, "wake_spread_min": None, "drift_min": None,
            "drift": None, "pattern": None}


def _kind(points: list, need: int, tz: Optional[tzinfo]) -> dict:
    """``points``: (day ordinal, (start_s, end_s)) of one source."""
    rows = []
    for d, (a, b) in points:
        mid, wake = _minute((a + b) / 2, tz), _minute(b, tz)
        if mid is not None and wake is not None:
            rows.append((d, mid, wake))
    if len(rows) < need or len(rows) < 2:
        return _unknown(len(rows))
    mean, mid_sd = _circ([m for _, m, _ in rows])
    _, wake_sd = _circ([w for _, _, w in rows])
    xs = [float(d) for d, _, _ in rows]
    ys = [_signed(m, mean) for _, m, _ in rows]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    drift_min = slope * (max(xs) - min(xs))
    resid = math.sqrt(sum((y - my - slope * (x - mx)) ** 2 for x, y in zip(xs, ys)) / len(ys))
    drift = "steady" if abs(drift_min) < DRIFT_MIN else "later" if drift_min > 0 else "earlier"
    if drift != "steady" and resid <= STEADY_SPREAD_MIN:
        pattern = drift
    elif max(mid_sd, wake_sd) > STEADY_SPREAD_MIN:
        pattern = "varies"
    else:
        pattern = "steady"
    return {"known": True, "nights": len(rows), "mid_spread_min": int(round(mid_sd)),
            "wake_spread_min": int(round(wake_sd)), "drift_min": int(round(drift_min)), "drift": drift,
            "pattern": pattern}


def regularity(nights, min_nights: int = MIN_NIGHTS, tz: Optional[tzinfo] = None) -> dict:
    """Each source's regularity over the last MAX_NIGHTS of ``nights`` (sleep.timed_nights); never raises."""
    if isinstance(min_nights, bool) or not isinstance(min_nights, int) or min_nights < 2:
        min_nights = MIN_NIGHTS
    named = []
    for n in nights if isinstance(nights, (list, tuple)) else ():
        d = _day(n.get("night")) if isinstance(n, dict) else None
        if d is not None:
            named.append((d, n))
    window = sorted(named, key=lambda x: x[0])[-MAX_NIGHTS:]
    out = {}
    for src in SOURCES:
        pts = [(d, sp) for d, n in window for sp in (_span(n.get(src)),) if sp is not None]
        try:
            out[src] = _kind(pts, min_nights, tz)
        except (ValueError, ZeroDivisionError, OverflowError):
            out[src] = _unknown(len(pts))
    return out


def _chosen(r) -> Optional[str]:
    """The source the words describe: the wearable when known, else the phone estimate, else None."""
    if not isinstance(r, dict):
        return None
    for src in SOURCES:
        k = r.get(src)
        if isinstance(k, dict) and k.get("known") is True and k.get("pattern") in WORDS:
            return src
    return None


def label(r) -> dict:
    """The T1 words for ``r`` (regularity()), with the source named; "unknown: <why>" when neither is known."""
    src = _chosen(r)
    if src is not None:
        return {"label": f"{NAMES[src]}: {WORDS[r[src]['pattern']]}", "tier": "T1", "modality": MODALITY[src]}
    seen = any(isinstance(r.get(s), dict) and isinstance(r[s].get("nights"), int) and r[s]["nights"] > 0
               for s in SOURCES) if isinstance(r, dict) else False
    return {"label": UNKNOWN_FEW if seen else UNKNOWN_NONE, "tier": "T1", "modality": "proxy"}


def clause(r) -> str:
    """The week review's digit-free regularity clause ("wearable says sleep times steady"); "" when unknown."""
    src = _chosen(r)
    return "" if src is None else f"{NAMES[src]} says {WORDS[r[src]['pattern']]}"
