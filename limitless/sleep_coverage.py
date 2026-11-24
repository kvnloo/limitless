"""Sleep coverage: on how many nights did the wearable record sleep? Read-only (north-star row five).

    real, demo = split_demo(rows, cfg)           # sleep file rows -> (non-demo rows, how many demo rows were dropped)
    a = audit(sleep.nights(wear, gaps, today, days, tz), target=0.8, demo=demo)
    # -> dict: T0 counts of wearable, phone-estimate-only and unknown nights, the goal, and one T1 label

The nights are sleep.nights over the ``days`` local nights before ``today`` (a night is named by the evening it
began), from the wearable sleep file (config ``sleep_file``, StateReader.sleep_rows) beside the phone unlock-gap
proxy (sleep.screen_gaps). Per night: wearable when a valid, non-demo wearable row names it; phone estimate only
when the proxy has a quiet span that evening and the wearable has none; unknown when neither says anything.
The proxy never counts as wearable. Demo and sample rows (mock_guard: a demo device id or name, an Open
Wearables seed user, config ``mock_device_patterns``; also a ``source`` text carrying one of those marks) are
dropped before any night is read and only their count is kept.

The goal is the uptime audit's rule (uptime_audit): the wearable share is over the whole window, so an unknown
night counts against the goal, never for it. "met" when the wearable nights reach ``target`` of the window
(rounded up), "not met" when even every unknown night being wearable would not, else "unknown"; fewer than
MIN_KNOWN_NIGHTS known nights is "unknown" and the label is the one word UNKNOWN.

Config: ``sleep_coverage_days`` (the window, a whole number of nights, default DAYS) and
``sleep_coverage_target`` (above zero and at most one, default TARGET, the scorecard's bar).
Tiers: the counts are T0 and stay in the dict; the label is T1 words with no digit. No clock-time rule, no
score, no advice. Pure: no clock, no file, no send. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import math
from typing import Iterable, Mapping, Optional

from . import mock_guard, sleep, uptime_audit

DAYS = 28
TARGET = sleep.MOST_SHARE        # wearable sleep on at least this share of nights: the scorecard's bar
DAYS_CONFIG, TARGET_CONFIG = "sleep_coverage_days", "sleep_coverage_target"
MIN_KNOWN_NIGHTS = uptime_audit.MIN_KNOWN_DAYS
UNKNOWN = "unknown"
GOAL_MET, GOAL_NOT_MET, GOAL_UNKNOWN = uptime_audit.GOAL_MET, uptime_audit.GOAL_NOT_MET, uptime_audit.GOAL_UNKNOWN
GOAL_WORDS = {GOAL_MET: "wearable goal met", GOAL_NOT_MET: "wearable goal not met",
              GOAL_UNKNOWN: "wearable goal unknown: too many nights with no sleep data"}
EVERY, MOST, HALF, SOME, FEW = "every night", "most nights", "about half the nights", "some nights", "few nights"
NO_WEARABLE = "no wearable sleep"
NO_FILE_REASON = 'no wearable sleep file: set "sleep_file" in config.json'
UNREADABLE_REASON = "the wearable sleep file is missing or cannot be read"
NO_NIGHTS_REASON = "no wearable night and no phone estimate in the audit window"
FEW_KNOWN_REASON = "fewer than a week of nights have wearable sleep or a phone estimate"


def window_days(cfg: Optional[Mapping] = None) -> int:
    """Config ``sleep_coverage_days`` (a whole number, at least one); anything else is DAYS."""
    v = cfg.get(DAYS_CONFIG) if isinstance(cfg, Mapping) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else DAYS


def target(cfg: Optional[Mapping] = None) -> float:
    """Config ``sleep_coverage_target`` (a number above zero and at most one); anything else is TARGET."""
    v = cfg.get(TARGET_CONFIG) if isinstance(cfg, Mapping) else None
    ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 < v <= 1
    return float(v) if ok else TARGET


def is_demo(row, cfg: Optional[Mapping] = None) -> bool:
    """A sleep file row from a demo or sample device: mock_guard over the row, or over its ``source`` text."""
    if mock_guard.is_mock(row, cfg):
        return True
    src = row.get("source") if isinstance(row, Mapping) else None
    return isinstance(src, str) and mock_guard.is_mock(src, cfg)


def split_demo(rows: Optional[Iterable], cfg: Optional[Mapping] = None) -> tuple:
    """(the rows that are not demo rows, in order; how many demo rows were dropped). Never raises."""
    real, n = [], 0
    for r in rows or ():
        if is_demo(r, cfg):
            n += 1
        else:
            real.append(r)
    return real, n


def audit(nights, target: float = TARGET, demo: int = 0) -> dict:
    """The coverage of ``nights`` (sleep.nights: ``{night, wearable, proxy}`` per night, oldest first).
    T0 counts, the goal and the T1 label; see the module doc. Never raises on odd input."""
    ns = [n for n in (nights if isinstance(nights, (list, tuple)) else ()) if isinstance(n, dict)]
    c = sleep.counts(ns)
    out = dict(c, window_nights=len(ns), known_nights=c["wearable_nights"] + c["proxy_only_nights"],
               target=target, demo_rows=max(int(demo or 0), 0))
    out["wearable_share"] = c["wearable_nights"] / len(ns) if ns else None
    out["goal"] = _goal(out)
    out["label"] = {"label": _words(out), "tier": "T1", "modality": "measured" if c["wearable_nights"] else "proxy"}
    return out


def _goal(out: dict) -> str:
    n = out["window_nights"]
    if not n or out["known_nights"] < MIN_KNOWN_NIGHTS:
        return GOAL_UNKNOWN
    need = uptime_audit.needed_days(n, out["target"])
    if out["wearable_nights"] >= need:
        return GOAL_MET
    if out["wearable_nights"] + out["unknown_nights"] < need:
        return GOAL_NOT_MET
    return GOAL_UNKNOWN


def quantity(k: int, n: int) -> str:
    """``k`` of ``n`` nights in words: every night, most nights, about half the nights, some nights, few nights."""
    if k >= n:
        return EVERY
    if 2 * k > n:
        return MOST
    if 5 * k >= 2 * n:
        return HALF
    return SOME if 5 * k >= n else FEW


def _words(out: dict) -> str:
    if out["known_nights"] < MIN_KNOWN_NIGHTS:
        return UNKNOWN
    n, w, p, u = out["window_nights"], out["wearable_nights"], out["proxy_only_nights"], out["unknown_nights"]
    parts = [f"wearable sleep on {quantity(w, n)}" if w else NO_WEARABLE]
    if p:
        parts.append(f"phone estimate on {quantity(p, n)}")
    if u:
        parts.append(f"no sleep data on {quantity(u, n)}")
    tail = [GOAL_WORDS[out["goal"]]] + ([mock_guard.LEFT_OUT] if out["demo_rows"] else [])
    return "; ".join([", ".join(parts)] + tail)
