"""Flow, weekly: deep-work minutes and feed leak per block-hour from an ActivityWatch DB copy. No score.

    w = week(aw_db, week_of, tz, blocks=None, work_apps=(...), feed_apps=(...))
    # {deep_min, block_hours, feed_leak_min, leak_per_block_hour, days_with_data, modality, evidence}

The week is the seven local days from ``week_of`` in ``tz`` (a tzinfo; None = this machine's zone).
Active time is the app-in-foreground spans (bucket type ``currentwindow``), cut to the not-afk spans when
the DB has an ``afkstatus`` bucket for the week. Overlapping spans count once.

- Deep work: active time in an app the person names as work (``work_apps``: an ``app`` or ``package``
  name, trimmed and case-folded; ``title:<text>`` matches inside the window title). No list = unknown.
- Feed leak: active time in a feed app (feeds_evidence.feed_apps) inside a focus block. ``blocks`` are
  ``(start_s, end_s)`` pairs or Glide-style ``{"start", "end"}`` dicts; no block in the covered days =
  leak unknown. Leak per block-hour is feed minutes over block hours; a clean block is 0, not unknown.

Nothing here judges the numbers: no score, no target, no grade. The DB is opened read-only
(``mode=ro``); nothing here writes, creates or locks it. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote

from .aw_reader import BUSY_TIMEOUT_S, CURRENT_WINDOW, NS

AFK = "afkstatus"
MODALITY = "measured"
DAYS = 7
TITLE = "title:"

_SPANS = (
    "SELECT b.type, e.starttime, e.endtime, e.data FROM events e JOIN buckets b ON b.id = e.bucketrow "
    "WHERE b.type IN (?, ?) AND typeof(e.starttime) = 'integer' AND typeof(e.endtime) = 'integer' "
    "AND e.starttime < ? AND e.endtime > ? ORDER BY e.starttime, e.id"
)


def _merge(spans: Iterable) -> list:
    out = []
    for s, e in sorted(x for x in spans if x[1] > x[0]):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def _cut(a: list, b: list) -> list:
    """The intersection of two merged span lists."""
    out, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        s, e = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if e > s:
            out.append((s, e))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def _total(spans: list) -> float:
    return sum(e - s for s, e in spans)


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _matcher(names: Iterable):
    """A span -> bool test for a work or feed list, or None when the list names nothing."""
    exact, titles = set(), []
    for v in names or ():
        w = v.strip().casefold() if isinstance(v, str) else ""
        if w.startswith(TITLE):
            if w[len(TITLE):].strip():
                titles.append(w[len(TITLE):].strip())
        elif w:
            exact.add(w)

    def match(span) -> bool:
        return bool(span["names"] & exact) or any(t in span["title"] for t in titles)

    return match if exact or titles else None


def _day_start(d: date, tz: Optional[tzinfo]) -> float:
    if tz is None:
        return datetime.combine(d, time()).timestamp()
    return datetime.combine(d, time(), tzinfo=tz).timestamp()


def _pair(b):
    if isinstance(b, dict):
        return _num(b.get("start")), _num(b.get("end"))
    if isinstance(b, (tuple, list)) and len(b) >= 2:
        return _num(b[0]), _num(b[1])
    return None, None


def _blocks(blocks) -> list:
    out = []
    for b in blocks or ():
        s, e = _pair(b)
        if s is not None and e is not None:
            out.append((s, e))
    return _merge(out)


def _read(path: Path, lo: float, hi: float):
    """(window spans, afk spans) overlapping [lo, hi), cut to it. An afk row is None (away)."""
    uri = "file:" + quote(str(path.resolve())) + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_S)
    try:
        rows = con.execute(_SPANS, (CURRENT_WINDOW, AFK, int(hi * NS), int(lo * NS))).fetchall()
    finally:
        con.close()
    windows, afk = [], []
    for btype, start, end, data in rows:
        try:
            d = json.loads(data) if data is not None else {}
        except (TypeError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        s, e = max(start / NS, lo), min(end / NS, hi)
        if e <= s:
            continue
        if btype == AFK:
            if d.get("status") == "not-afk":
                afk.append((s, e))
            elif d.get("status") == "afk":
                afk.append(None)
            continue
        names = {d[k].strip().casefold() for k in ("app", "package") if isinstance(d.get(k), str)} - {""}
        title = d["title"].casefold() if isinstance(d.get("title"), str) else ""
        windows.append({"s": s, "e": e, "names": names, "title": title})
    return windows, afk


def week(aw_db, week_of, tz: Optional[tzinfo], blocks=None, *, work_apps: Iterable = (),
         feed_apps: Iterable = ()) -> dict:
    """The week's flow numbers; every unknown is None with its reason in ``evidence``."""
    start = week_of if isinstance(week_of, date) else date.fromisoformat(str(week_of))
    bounds = [_day_start(start + timedelta(days=i), tz) for i in range(DAYS + 1)]
    lo, hi = bounds[0], bounds[-1]
    windows, afk_rows = _read(Path(aw_db), lo, hi)
    seen = [i for i in range(DAYS) if any(w["s"] < bounds[i + 1] and w["e"] > bounds[i] for w in windows)]
    covered = _merge((bounds[i], bounds[i + 1]) for i in seen)
    days = [(start + timedelta(days=i)).isoformat() for i in seen]
    afk = _merge(x for x in afk_rows if x is not None)

    def active(spans) -> list:
        return _cut(_merge(spans), afk) if afk_rows else _merge(spans)

    evidence = {"source": "activitywatch", "days": days, "afk_cut": bool(afk_rows)}
    out = {"deep_min": None, "block_hours": None, "feed_leak_min": None, "leak_per_block_hour": None,
           "days_with_data": len(days), "modality": MODALITY, "evidence": evidence}

    work = _matcher(work_apps)
    if work is None:
        evidence["deep"] = "unknown: no work apps set (flow_work_apps)"
    else:
        out["deep_min"] = round(_total(active((w["s"], w["e"]) for w in windows if work(w))) / 60, 1)
        evidence["deep"] = "active time in the configured work apps"

    data_end = max((w["e"] for w in windows), default=lo)
    block = _cut(_cut(_blocks(blocks), covered), [(lo, data_end)])
    if not block:
        evidence["leak"] = "unknown: no focus blocks on days with data"
        return out
    block_h = _total(block) / 3600
    out["block_hours"] = round(block_h, 2)
    feed = _matcher(feed_apps)
    if feed is None:
        evidence["leak"] = "unknown: no feed apps set (feed_apps)"
        return out
    leak_min = _total(_cut(active((w["s"], w["e"]) for w in windows if feed(w)), block)) / 60
    out["feed_leak_min"] = round(leak_min, 1)
    out["leak_per_block_hour"] = round(leak_min / block_h, 1)
    evidence["leak"] = "feed-app active time inside focus blocks"
    return out
