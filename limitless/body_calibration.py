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


MIN_PAIRS = 2
MIN_LINEAR_PAIRS = 5
FITTED = "calibrated against reference scans"
NO_FIT = "uncalibrated: fewer than two reference scans paired with a scale reading"
WORDS = (FITTED, NO_FIT)


def _offset(ps: list) -> float:
    return float(statistics.median(p["reference"] - p["scale"] for p in ps))


def _line(ps: list) -> Optional[tuple]:
    """Least squares ``reference = intercept + slope * scale``; None when the scale values do not vary."""
    xs, ys = [p["scale"] for p in ps], [p["reference"] for p in ps]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-12:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - slope * mx, slope


def _loo(ps: list) -> tuple:
    """Mean absolute leave-one-out error of the offset and of the line (None when a line cannot be fitted)."""
    off, lin = [], []
    for i, p in enumerate(ps):
        rest = ps[:i] + ps[i + 1:]
        off.append(abs(p["scale"] + _offset(rest) - p["reference"]))
        line = _line(rest)
        if line is None:
            lin = None
        elif lin is not None:
            lin.append(abs(line[0] + line[1] * p["scale"] - p["reference"]))
    return statistics.fmean(off), (statistics.fmean(lin) if lin else None)


def fit(rows, methods: Optional[Iterable[str]] = None, pair_days: int = PAIR_DAYS) -> dict:
    """The simplest model the pairs support; never raises.

    ``{"model": "offset"|"linear"|None, "pairs": int, "offset", "slope", "intercept", "loo_offset",
    "loo_linear", "methods": [...], "label": T1}``. Under MIN_PAIRS pairs: model None (no calibration). Else
    a constant offset (the median of reference minus scale). A line only with MIN_LINEAR_PAIRS or more pairs
    and only when its leave-one-out error is strictly lower than the offset's. Numbers are T0; the label
    has no digit.
    """
    ps = pairs(rows, methods, pair_days)
    out = {"model": None, "pairs": len(ps), "offset": None, "slope": None, "intercept": None,
           "loo_offset": None, "loo_linear": None, "methods": sorted(_methods(methods)),
           "label": {"label": NO_FIT, "tier": "T1"}}
    if len(ps) < MIN_PAIRS:
        return out
    out.update(model="offset", offset=_offset(ps), label={"label": FITTED, "tier": "T1"})
    if len(ps) >= MIN_LINEAR_PAIRS:
        loo_off, loo_lin = _loo(ps)
        out.update(loo_offset=loo_off, loo_linear=loo_lin)
        line = _line(ps)
        if loo_lin is not None and line is not None and loo_lin < loo_off:
            out.update(model="linear", intercept=line[0], slope=line[1])
    return out


def predict(f, bf: float) -> Optional[float]:
    """The scale reading ``bf`` corrected by fit ``f``; None when ``f`` is no fit."""
    if not isinstance(f, dict):
        return None
    if f.get("model") == "linear":
        return f["intercept"] + f["slope"] * bf
    if f.get("model") == "offset":
        return bf + f["offset"]
    return None


def calibrated_rows(rows, f) -> list:
    """``rows`` with every scale row corrected by fit ``f`` and marked ``calibrated: true`` (its day and method
    kept); reference rows and rows already calibrated pass through unchanged. Pure: a new list of new dicts,
    ``rows`` is not touched. No fit is the rows as they were."""
    rows = list(rows) if isinstance(rows, (list, tuple)) else []
    methods = f.get("methods") if isinstance(f, dict) else None
    out = []
    for r in rows:
        r = dict(r) if isinstance(r, dict) else r
        if isinstance(r, dict) and _body._valid(r) and is_scale(r, methods):
            v = predict(f, r["bf_pct"])
            if v is not None:
                r.update(bf_pct=v, calibrated=True)
        out.append(r)
    return out
