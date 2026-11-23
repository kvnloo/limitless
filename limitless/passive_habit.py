"""Passively measured habit days: what the phone saw, shown next to the confirmed habit week, never instead of it.

    summary(rows, first, last) -> {"days_measured", "days_met", "modality": "proxy", "label"} | None
    view(reader, first, last, env, home) -> the same, from StateReader.passive_habit_days()

An older loop writes one row per day (``{"day", "met": bool, ...}``) to the file named by config
``passive_habit_file``: was the first hour after the wake feed-free? That is a measurement of phone data,
a proxy: it never starts, logs or closes a habit week. Only habit.json (habit_start, the person's taps)
does that, and the week review's "N of M logged days" stays the tapped number.

Unknown is not zero: no file configured, or no valid row between ``first`` and ``last``, is None (no
passive field at all), never "0 of 0". The label is T1 (no digit): fewer than MIN_DAYS measured days is
"not enough phone data"; else the first hour was mostly (at least two thirds of the measured days),
rarely (at most one third) or about half the time feed-free. Words only: no score, no clock-time rule
(the wake is an event, read by the older loop). Nothing here writes or sends. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Mapping, Optional

MODALITY = "proxy"
MIN_DAYS = 3
WINDOW_DAYS = 7          # with no confirmed week: today and the six days before it
NOT_ENOUGH = "not enough phone data"
NOT_STARTED = "habit not started"


def summary(rows, first: date, last: date) -> Optional[dict]:
    """Counts of the rows whose day is in [first, last]; None when there is none (unknown, not zero)."""
    lo, hi = first.isoformat(), last.isoformat()
    days = {}
    for r in rows or ():
        if isinstance(r, dict) and isinstance(r.get("day"), str) and isinstance(r.get("met"), bool) \
                and lo <= r["day"] <= hi:
            days[r["day"]] = r["met"]
    if not days:
        return None
    out = {"days_measured": len(days), "days_met": sum(days.values()), "modality": MODALITY}
    out["label"] = {"label": phrase(out), "tier": "T1", "modality": MODALITY}
    return out


def phrase(s: Optional[dict]) -> str:
    """The digit-free words for a summary: not enough phone data, or what phone data shows."""
    n, met = (s or {}).get("days_measured") or 0, (s or {}).get("days_met") or 0
    if n < MIN_DAYS:
        return NOT_ENOUGH
    if met * 3 >= n * 2:
        return "phone data shows the first hour mostly feed-free"
    if met * 3 <= n:
        return "phone data shows the first hour rarely feed-free"
    return "phone data shows the first hour feed-free about half the time"


def not_started_label(s: dict) -> dict:
    """The T1 label for a result with no confirmed week: "habit not started; <phrase>"."""
    return {"label": f"{NOT_STARTED}; {phrase(s)}", "tier": "T1", "modality": MODALITY}


def review_line(s: Optional[dict]) -> str:
    """The week review's second line, digit-free; "" when there is no passive data for the week."""
    if s is None:
        return ""
    words = phrase(s)
    if words == NOT_ENOUGH:
        return "Phone data (a proxy, not a check-in): not enough this week to say."
    words = words[len("phone data shows "):] if words.startswith("phone data shows ") else words
    return f"Phone data (a proxy, not a check-in): {words}."


def view(reader, first: date, last: date, env: Optional[Mapping[str, str]] = None,
         home: Optional[Path] = None) -> Optional[dict]:
    """summary() of the reader's passive habit days; None on any read problem (unknown, never a guess)."""
    try:
        rows = reader.passive_habit_days(env, home)
    except Exception:  # noqa: BLE001 - an unreadable passive file is unknown, never a traceback
        return None
    return summary(rows, first, last)
