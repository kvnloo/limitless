"""Sleep, nightly and in words only: the wearable summary and the phone proxy side by side, never mixed.

    ns = nights(wearable_rows, proxy_gaps, today, days=7, tz=None)
    # [{"night": "YYYY-MM-DD", "wearable": asleep_s | None, "proxy": gap_s | None}, ...] oldest first
    lab = label(ns, modality)   # T1 dict: "sleep: wearable on most nights; phone proxy says longer"
    ts = timed_nights(wearable_rows, proxy_gaps, today, days=14, tz=None)
    # [{"night", "wearable": (start_s, end_s) | None, "proxy": (start_s, end_s) | None}, ...] for regularity.py

A night is named by the evening it began (local date). The nights are the ``days`` before ``today``.
``wearable_rows`` are StateReader.sleep_rows(): ``{"night", "asleep_s", "source"}``; when two sources describe
one night, the first row wins. ``proxy_gaps`` are ``(from_s, to_s)`` quiet spans between the person's own
phone actions (screen_gaps over jobs_runner.person_rows, the rows the screen wakes use: wake_proxy.person_times).
A night's proxy is the longest gap that starts in the evening half (noon on, local time) of its date; a gap of
MAX_GAP_S or more is missing data (a dead or unsynced phone), not sleep. The proxy is a quiet phone, not a
sleep measure: it is reported beside the wearable, never in its place. A night with neither is unknown
(None), never zero.

Words: "sleep: wearable on most nights | some nights | no nights" (most = at least MOST_SHARE of the nights,
the scorecard's bar), then "phone proxy says about the same | shorter | longer" (the median, over nights with
both, of proxy minus wearable, within ABOUT_SAME_S is about the same) or "phone proxy has no night to compare".

Tiers: seconds and counts are T0 and stay in code; ``label`` and ``review_line`` are T1 words with no digit.
No target, no advice, no clock-time rule. Nothing here reads the clock, touches a file or sends.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Optional

from . import regularity, wake_proxy

DAYS = 7
REGULARITY_DAYS = 14         # regularity reads the last two weeks of nights (timed_nights)
EVENING_FROM_H = 12          # a gap that starts at or after local noon belongs to that date's night
MAX_GAP_S = 24 * 3600        # a quiet span this long is missing data, not a night
ABOUT_SAME_S = 30 * 60       # proxy and wearable within this (median over nights with both) say the same
MOST_SHARE = 0.8             # the scorecard criterion: wearable sleep on at least this share of nights
COVERAGE = ("most nights", "some nights", "no nights")
COMPARES = ("says about the same", "says shorter", "says longer", "has no night to compare")
LABELS = tuple(f"sleep: wearable on {c}; phone proxy {k}" for c in COVERAGE for k in COMPARES)


def screen_gaps(rows) -> list:
    """``(from_s, to_s)`` quiet spans between consecutive person actions in screen-event rows, oldest first.
    A span of MAX_GAP_S or more is a hole in the data (a dead or unsynced phone), not a gap: it is left out."""
    try:
        times = wake_proxy.person_times(rows if isinstance(rows, (list, tuple)) else [])
    except Exception:  # noqa: BLE001 - a bad row list is no gaps
        return []
    return [(a, b) for a, b in zip(times, times[1:]) if 0 < b - a < MAX_GAP_S]


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _gap(g) -> Optional[tuple]:
    if not isinstance(g, (list, tuple)) or len(g) != 2:
        return None
    a, b = _num(g[0]), _num(g[1])
    if a is None or b is None or not 0 < b - a < MAX_GAP_S:
        return None
    return a, b


def _evening_night(start: float, tz: Optional[tzinfo]) -> Optional[str]:
    try:
        dt = datetime.fromtimestamp(start, tz)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.date().isoformat() if dt.hour >= EVENING_FROM_H else None


def _names(today, days) -> list:
    if not isinstance(today, date) or isinstance(days, bool) or not isinstance(days, int) or days < 1:
        return []
    return [(today - timedelta(days=a)).isoformat() for a in range(days, 0, -1)]


def _wear_rows(wearable_rows, wanted) -> dict:
    """night -> its first valid wearable row (a positive int ``asleep_s``)."""
    wear = {}
    for r in wearable_rows if isinstance(wearable_rows, (list, tuple)) else ():
        if not isinstance(r, dict) or r.get("night") not in wanted or r["night"] in wear:
            continue
        s = r.get("asleep_s")
        if not isinstance(s, bool) and isinstance(s, int) and s > 0:
            wear[r["night"]] = r
    return wear


def _proxy_spans(proxy_gaps, wanted, tz) -> dict:
    """night -> its proxy: the longest valid gap that starts in the evening half of its date."""
    proxy = {}
    for g in proxy_gaps if isinstance(proxy_gaps, (list, tuple)) else ():
        g = _gap(g)
        n = _evening_night(g[0], tz) if g is not None else None
        if n in wanted and (n not in proxy or g[1] - g[0] > proxy[n][1] - proxy[n][0]):
            proxy[n] = g
    return proxy


def nights(wearable_rows, proxy_gaps, today: date, days: int = DAYS, tz: Optional[tzinfo] = None) -> list:
    """One ``{night, wearable, proxy}`` per night in the ``days`` before ``today``, oldest first; never raises."""
    names = _names(today, days)
    wear, proxy = _wear_rows(wearable_rows, set(names)), _proxy_spans(proxy_gaps, set(names), tz)
    return [{"night": n, "wearable": wear[n]["asleep_s"] if n in wear else None,
             "proxy": int(round(proxy[n][1] - proxy[n][0])) if n in proxy else None} for n in names]


def timed_nights(wearable_rows, proxy_gaps, today: date, days: int = REGULARITY_DAYS,
                 tz: Optional[tzinfo] = None) -> list:
    """When each night ran, for regularity.regularity: ``{night, wearable, proxy}`` with each a ``(start_s,
    end_s)`` span or None, per night in the ``days`` before ``today``, oldest first; never raises. The wearable
    span is the night's first valid row's ``span`` (StateReader.sleep_rows; None when that row has no times),
    the proxy span the same gap ``nights`` measures."""
    names = _names(today, days)
    wear, proxy = _wear_rows(wearable_rows, set(names)), _proxy_spans(proxy_gaps, set(names), tz)
    return [{"night": n, "wearable": _gap(wear[n].get("span")) if n in wear else None, "proxy": proxy.get(n)}
            for n in names]


def _valid(ns) -> list:
    return [n for n in (ns if isinstance(ns, (list, tuple)) else ()) if isinstance(n, dict)]


def counts(ns) -> dict:
    """Nights with the wearable, with the phone proxy only, and with neither (unknown)."""
    ns = _valid(ns)
    w = sum(1 for n in ns if n.get("wearable") is not None)
    p = sum(1 for n in ns if n.get("wearable") is None and n.get("proxy") is not None)
    return {"wearable_nights": w, "proxy_only_nights": p, "unknown_nights": len(ns) - w - p}


def _t1(word: str, modality: str) -> dict:
    return {"label": word, "tier": "T1", "modality": modality}


def label(ns, modality: str = "proxy") -> dict:
    """The T1 words for ``ns`` (nights()): wearable coverage, then what the phone proxy says beside it."""
    ns = _valid(ns)
    c = counts(ns)
    n = c["wearable_nights"]
    cov = COVERAGE[2] if n == 0 else COVERAGE[0] if ns and n / len(ns) >= MOST_SHARE else COVERAGE[1]
    diffs = [x["proxy"] - x["wearable"] for x in ns if x.get("wearable") is not None and x.get("proxy") is not None]
    if not diffs:
        cmp = COMPARES[3]
    else:
        d = statistics.median(diffs)
        cmp = COMPARES[0] if abs(d) <= ABOUT_SAME_S else COMPARES[1] if d < 0 else COMPARES[2]
    return _t1(f"sleep: wearable on {cov}; phone proxy {cmp}", modality)


def _night_end(night: str, tz: Optional[tzinfo]) -> Optional[float]:
    """The local midnight that ends a night's evening: a wearable night is never dated fresher than this."""
    try:
        d = date.fromisoformat(night) + timedelta(days=1)
        dt = datetime.combine(d, time(0))
        return (dt.replace(tzinfo=tz) if tz is not None else dt).timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def newest_at(wearable_rows, proxy_gaps, tz: Optional[tzinfo] = None) -> Optional[float]:
    """Epoch seconds of the newest datum: a gap's end, or a wearable night's local midnight; None when none."""
    best = None
    for r in wearable_rows if isinstance(wearable_rows, (list, tuple)) else ():
        t = _night_end(r.get("night"), tz) if isinstance(r, dict) else None
        best = t if t is not None and (best is None or t > best) else best
    for g in proxy_gaps if isinstance(proxy_gaps, (list, tuple)) else ():
        g = _gap(g)
        best = g[1] if g is not None and (best is None or g[1] > best) else best
    return best


def review_line(lab, reg=None) -> str:
    """The week review's sleep line, digit-free; "" for anything that is not one of LABELS. ``reg``
    (regularity.regularity) adds one regularity clause after the words ("...; wearable says sleep times
    steady."); none when it is unknown or missing."""
    word = lab.get("label") if isinstance(lab, dict) else None
    if not isinstance(word, str) or word not in LABELS:
        return ""
    extra = regularity.clause(reg)
    return f"{word[0].upper()}{word[1:]}{'; ' + extra if extra in regularity.CLAUSES else ''}."
