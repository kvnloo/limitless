"""Body-composition trend, weekly and in words only: is body fat trending down, flat or up?

    t = trend(rows, today, flat=FLAT_POINTS)
    # {"direction": down|flat|up|None, "modality": measured|proxy, "change": float|None,
    #  "recent": {"rows", "median"}, "prior": {"rows", "median"}, "label": T1 dict}

Rows are StateReader.body_rows(): one per measurement visit, ``{"day", "bf_pct", "method", "calibrated"}``.
The recent window is ``today`` and the RECENT_DAYS - 1 days before it; the prior window is the WINDOW_DAYS
days before that. The median of each window is compared (a single odd visit does not move it); a change
under ``flat`` points (config ``body_flat_points``, default FLAT_POINTS) is flat. Fewer than MIN_ROWS rows
in either window is "not enough measurements": unknown, never a guess.

Modality: "measured" when every row in both windows is calibrated (the app's estimate is fitted against
reference scans), else "proxy". The label says which: "(calibrated estimate)" or "(uncalibrated estimate)".

Tiers: the numbers here are T0 and stay in code; ``label`` and ``review_line`` are T1 words with no digit.
No score, no target, no goal, no advice: a direction only. Nothing here reads the clock, writes or sends.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from pathlib import Path
from typing import Mapping, Optional

from .state_reader import config

WINDOW_DAYS = 14
MIN_ROWS = 3
FLAT_POINTS = 0.5
FLAT_CONFIG = "body_flat_points"
NOT_ENOUGH = "not enough measurements"
CALIBRATED, UNCALIBRATED = "calibrated estimate", "uncalibrated estimate"
DIRECTIONS = ("down", "flat", "up")
LABELS = (NOT_ENOUGH,) + tuple(f"body fat trending {d} ({c})" for d in DIRECTIONS for c in (CALIBRATED, UNCALIBRATED))


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def flat_points(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> float:
    """config ``body_flat_points`` (a finite number >= 0), else FLAT_POINTS. Wording only, not a target."""
    v = _num(config(env, home).get(FLAT_CONFIG))
    return v if v is not None and v >= 0 else FLAT_POINTS


def _valid(r) -> bool:
    if not isinstance(r, dict) or _num(r.get("bf_pct")) is None or not isinstance(r.get("calibrated"), bool):
        return False
    try:
        date.fromisoformat(r.get("day"))
    except (TypeError, ValueError):
        return False
    return True


def _window(rows: list, first: date, last: date) -> list:
    lo, hi = first.isoformat(), last.isoformat()
    return [r for r in rows if lo <= r["day"] <= hi]


def _side(rows: list) -> dict:
    return {"rows": len(rows), "median": statistics.median(r["bf_pct"] for r in rows) if rows else None}


def _t1(word: str, modality: str) -> dict:
    return {"label": word, "tier": "T1", "modality": modality}


def trend(rows, today: date, flat: float = FLAT_POINTS) -> dict:
    """The trend of ``rows`` up to ``today``; never raises (bad input reads as not enough measurements)."""
    flat = _num(flat)
    flat = FLAT_POINTS if flat is None or flat < 0 else flat
    valid = [r for r in (rows if isinstance(rows, (list, tuple)) else ()) if _valid(r)]
    if isinstance(today, date):
        recent = _window(valid, today - timedelta(days=WINDOW_DAYS - 1), today)
        prior = _window(valid, today - timedelta(days=2 * WINDOW_DAYS - 1), today - timedelta(days=WINDOW_DAYS))
    else:
        recent, prior = [], []
    both = recent + prior
    modality = "measured" if both and all(r["calibrated"] for r in both) else "proxy"
    out = {"direction": None, "modality": modality, "change": None, "recent": _side(recent), "prior": _side(prior)}
    if len(recent) < MIN_ROWS or len(prior) < MIN_ROWS:
        out["label"] = _t1(NOT_ENOUGH, modality)
        return out
    change = out["recent"]["median"] - out["prior"]["median"]
    direction = "flat" if abs(change) < flat else "down" if change < 0 else "up"
    out.update(direction=direction, change=round(change, 2))
    out["label"] = _t1(f"body fat trending {direction} ({CALIBRATED if modality == 'measured' else UNCALIBRATED})",
                       modality)
    return out


def review_line(t: Optional[dict]) -> str:
    """The week review's body line, digit-free; "" when there is no trend at all."""
    word = ((t or {}).get("label") or {}).get("label") if isinstance(t, dict) else None
    if word not in LABELS:
        return ""
    if word == NOT_ENOUGH:
        return f"Body fat: {NOT_ENOUGH}."
    return f"{word[0].upper()}{word[1:]}."
