"""Calibrate the scale's body-fat estimate against reference scans, from the same body file.

    p = pairs(rows, methods=REFERENCE_METHODS, pair_days=PAIR_DAYS)
    # [{"day", "reference": float, "scale_day", "scale": float, "gap_days": int}], oldest first

A consumer scale's body-fat number is not trusted alone; a reference scan (``method`` in config
``body_reference_methods``, default dxa, case-blind) is. Each reference row is paired with the scale rows
of the nearest day within ``body_pair_days`` (config, default PAIR_DAYS) of it: the same day first, then
the nearest day; a tie takes the earlier day. Several scale rows on that day count as their median. A scale
row is any other row whose ``calibrated`` is false (a row already calibrated outside is left alone).

Tiers: every number here is T0 and stays in code. Nothing here reads the clock, writes or sends.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import statistics
from datetime import date
from typing import Iterable, Optional

from . import body as _body

REFERENCE_METHODS = ("dxa",)
PAIR_DAYS = 3


def _methods(methods: Optional[Iterable[str]]) -> frozenset:
    if methods is None or isinstance(methods, str):
        methods = REFERENCE_METHODS
    return frozenset(m.strip().lower() for m in methods if isinstance(m, str) and m.strip())


def _valid(rows) -> list:
    if not isinstance(rows, (list, tuple)):
        return []
    return [r for r in rows if _body._valid(r) and isinstance(r.get("method"), str)]


def is_reference(row, methods: Optional[Iterable[str]] = None) -> bool:
    """True when ``row``'s method is a reference method (case-blind)."""
    return isinstance(row, dict) and isinstance(row.get("method"), str) \
        and row["method"].strip().lower() in _methods(methods)


def is_scale(row, methods: Optional[Iterable[str]] = None) -> bool:
    """True when ``row`` is a scale row: not a reference row and not already calibrated."""
    return isinstance(row, dict) and not is_reference(row, methods) and row.get("calibrated") is False


def pairs(rows, methods: Optional[Iterable[str]] = None, pair_days: int = PAIR_DAYS) -> list:
    """Each reference row with the nearest scale day within ``pair_days``; never raises."""
    if isinstance(pair_days, bool) or not isinstance(pair_days, int) or pair_days < 0:
        pair_days = PAIR_DAYS
    valid = _valid(rows)
    by_day: dict = {}
    for r in valid:
        if is_scale(r, methods):
            by_day.setdefault(r["day"], []).append(r["bf_pct"])
    days = sorted(by_day)
    out = []
    for r in sorted((r for r in valid if is_reference(r, methods)), key=lambda r: r["day"]):
        d = date.fromisoformat(r["day"])
        best = None
        for s in days:   # oldest first, so a strict < keeps the earlier day on a tie
            gap = abs((date.fromisoformat(s) - d).days)
            if gap <= pair_days and (best is None or gap < best[0]):
                best = (gap, s)
        if best is not None:
            out.append({"day": r["day"], "reference": r["bf_pct"], "scale_day": best[1],
                        "scale": float(statistics.median(by_day[best[1]])), "gap_days": best[0]})
    return out
