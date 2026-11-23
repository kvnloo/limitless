"""Calibrate the scale's body-fat estimate against reference scans, from the same body file.

    p = pairs(rows, methods=REFERENCE_METHODS, pair_days=PAIR_DAYS)
    # [{"day", "reference": float, "scale_day", "scale": float, "gap_days": int}], oldest first

A consumer scale's body-fat number is not trusted alone; a reference scan (``method`` in config
``body_reference_methods``, default dxa, case-blind) is. Each reference row is paired with the scale rows
of the nearest day within ``body_pair_days`` (config, default PAIR_DAYS) of it: the same day first, then
the nearest day; a tie takes the earlier day. Several scale rows on that day count as their median. A scale
row is any other row whose ``calibrated`` is false (a row already calibrated outside is left alone).

Wiring: ``trend(rows, today, env, home)`` is body.trend over ``calibrated_rows`` when a fit exists (config
``body_calibration``, on by default; "off" is body.trend exactly), and ``review_line`` is the week
review's digit-free line. With no reference row at all nothing changes.

Tiers: every number here is T0 and stays in code: never in a label, never in a prompt. Nothing here reads the clock, writes or sends.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import statistics
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping, Optional

from . import body as _body
from .state_reader import config

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
FITTED = _body.REFERENCE_CALIBRATED
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


MODE_CONFIG = "body_calibration"
METHODS_CONFIG = "body_reference_methods"
PAIR_DAYS_CONFIG = "body_pair_days"
MODES = ("on", "off")


def mode(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> str:
    """config ``body_calibration``: "off" (case-blind) is off; anything else is "on" (a fit is used when one
    exists, else nothing changes)."""
    v = config(env, home).get(MODE_CONFIG)
    return "off" if isinstance(v, str) and v.strip().lower() == "off" else "on"


def reference_methods(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> list:
    """config ``body_reference_methods``: a non-empty list of non-empty strings, else ["dxa"]."""
    v = config(env, home).get(METHODS_CONFIG)
    if isinstance(v, list) and v and all(isinstance(m, str) and m.strip() for m in v):
        return list(v)
    return list(REFERENCE_METHODS)


def pair_days(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> int:
    """config ``body_pair_days``: a whole number of days >= 0, else PAIR_DAYS."""
    v = config(env, home).get(PAIR_DAYS_CONFIG)
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else PAIR_DAYS


def for_trend(rows, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> tuple:
    """``(rows the trend reads, fit or None)``. None, with ``rows`` as given, when calibration is off or no
    row is a reference scan: today's trend exactly. Else the fit, and calibrated rows when it has a model."""
    if mode(env, home) == "off":
        return rows, None
    methods = reference_methods(env, home)
    if not any(is_reference(r, methods) for r in _valid(rows)):
        return rows, None
    f = fit(rows, methods, pair_days(env, home))
    return (calibrated_rows(rows, f) if f["model"] else rows), f


def trend(rows, today: date, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> dict:
    """body.trend over the rows for_trend gives. With a fit the words say "(calibrated against reference
    scans)" where the trend is measured, and ``calibration`` holds the fit's T1 words (a no-fit says why).
    Without a fit or with calibration off: body.trend's result exactly. Never raises."""
    rows, f = for_trend(rows, env, home)
    t = _body.trend(rows, today, flat=_body.flat_points(env, home))
    if f is None:
        return t
    t["calibration"] = dict(f["label"])
    if f["model"] and t["direction"] and t["modality"] == "measured":
        t["label"] = dict(t["label"], label=f"body fat trending {t['direction']} ({FITTED})")
    return t


def review_line(t: Optional[dict]) -> str:
    """The week review's body line, digit-free: body.review_line, then the no-fit sentence when reference
    scans exist but fewer than two pair with a scale reading. "" when there is no trend."""
    line = _body.review_line(t)
    cal = ((t or {}).get("calibration") or {}).get("label") if isinstance(t, dict) else None
    if line and cal == NO_FIT:
        line += f" {NO_FIT[0].upper()}{NO_FIT[1:]}."
    return line
