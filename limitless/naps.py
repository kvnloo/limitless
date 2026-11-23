"""Naps, in words only: yesterday's short daytime Sleep-mode spans, never the night, never advice.

    ns = naps(events, since_s, until_s, nap_max_h=NAP_MAX_H, tz=None)
    # [{"start_s", "end_s"}, ...] oldest first, or None (unknown: no Sleep-mode event in the range)

``events`` are Sleep-mode events ``{"event": "sleep_mode_on" | "sleep_mode_off", "at"}`` (jobs.events_from_sleepmode
over StateReader.sleepmode(); other events are ignored). Each "on" followed by an "off" is one sleep period (the
first "on" of a run counts, as jobs._sleep_spans). A period is a nap when it is shorter than ``nap_max_h`` (config
``nap_max_h``, default NAP_MAX_H = two hours) and is not the longest sleep period of its local day. A period's day
is the local date it ended on, so the night that ended this morning is in this day: a short night alone in its day
is the night, not a nap, and a nap before a night that starts after midnight still counts. An "on" with no "off"
yet is open, not a nap. A nap is in the range when it ended in ``[since_s, until_s)``.

Unknown is None, never zero: no Sleep-mode event in the range means nothing is known about naps there. Sleep mode
is a phone switch the person flips, not a sleep sensor: modality "proxy".

NAP_MAX_H is not jobs.NAP_MAX_S: that one (three hours) decides when "Back from nap" may send after an off; this one
decides what the ledger calls a nap. Seconds and counts are T0 and stay in code. Nothing here reads the clock,
touches a file or sends. No target, no advice on how long or when to nap. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import math
from datetime import datetime, tzinfo
from typing import Mapping, Optional

from .state_reader import parse_ts

NAP_MAX_H = 2.0              # a Sleep-mode period this long or longer is sleep, not a nap
MAX_CONFIG_H = 24.0          # a configured nap_max_h above this is a typo: the default is used
CONFIG_KEY = "nap_max_h"
MAX_SPAN_S = 24 * 3600       # a period this long or longer is a hole in the data, not sleep
_SLEEP = ("sleep_mode_on", "sleep_mode_off")


def _hours(cfg: Optional[Mapping], key: str, default: float) -> float:
    v = cfg.get(key) if isinstance(cfg, Mapping) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 < v <= MAX_CONFIG_H:
        return default
    return float(v)


def nap_max_h(cfg: Optional[Mapping]) -> float:
    """Config ``nap_max_h`` when it is a number of hours in (0, 24], else NAP_MAX_H."""
    return _hours(cfg, CONFIG_KEY, NAP_MAX_H)


def _num(v) -> Optional[float]:
    return v if isinstance(v, float) and math.isfinite(v) else None


def _sleep_events(events) -> list:
    """(at, name) of the valid Sleep-mode events, oldest first."""
    out = []
    for e in events if isinstance(events, (list, tuple)) else ():
        if not isinstance(e, dict) or e.get("event") not in _SLEEP:
            continue
        t = _num(parse_ts(e.get("at")))
        if t is not None:
            out.append((t, e["event"]))
    return sorted(out)


def periods(events) -> list:
    """(on_at, off_at) of each closed Sleep-mode period under MAX_SPAN_S, oldest first; an open "on" is left out."""
    spans, start = [], None
    for t, name in _sleep_events(events):
        if name == "sleep_mode_on":
            start = t if start is None else start
        elif start is not None:
            if 0 < t - start < MAX_SPAN_S:
                spans.append((start, t))
            start = None
    return spans


def _day(t: float, tz: Optional[tzinfo]):
    try:
        return datetime.fromtimestamp(t, tz).date()
    except (OverflowError, OSError, ValueError):
        return None


def nap_periods(events, nap_max_h: float = NAP_MAX_H, tz: Optional[tzinfo] = None) -> list:
    """Every closed period that is a nap (shorter than ``nap_max_h``, not the longest of its local day)."""
    if isinstance(nap_max_h, bool) or not isinstance(nap_max_h, (int, float)) or not nap_max_h > 0:
        nap_max_h = NAP_MAX_H
    spans = periods(events)
    longest = {}
    for a, b in spans:
        d = _day(b, tz)
        if d is not None and (d not in longest or b - a > longest[d][1] - longest[d][0]):
            longest[d] = (a, b)
    return [(a, b) for a, b in spans
            if b - a < nap_max_h * 3600 and _day(b, tz) is not None and longest.get(_day(b, tz)) != (a, b)]


def naps(events, since_s, until_s, nap_max_h: float = NAP_MAX_H, tz: Optional[tzinfo] = None) -> Optional[list]:
    """The naps that ended in ``[since_s, until_s)``, ``{start_s, end_s}`` oldest first; None (unknown) when no
    Sleep-mode event falls in the range. Never raises."""
    lo, hi = parse_ts(since_s), parse_ts(until_s)
    if lo is None or hi is None or not hi > lo:
        return None
    try:
        if not any(lo <= t < hi for t, _ in _sleep_events(events)):
            return None
        return [{"start_s": a, "end_s": b} for a, b in nap_periods(events, nap_max_h, tz) if lo <= b < hi]
    except Exception:  # noqa: BLE001 - bad Sleep-mode rows are unknown, never a traceback
        return None
