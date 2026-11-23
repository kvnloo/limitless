"""Flow metrics: how broken up the work was, per day, from app-activity rows. Observed activity, no score.

    days = metrics(rows, work_apps, gap_s, break_after_s=..., tz=None)   # [per-day dict], None for unknown

A row is ``{"start", "end"}`` (epoch seconds) with the app's ``app`` / ``package`` names and ``title`` (or
``names``), as blocks.read_rows gives them. Work rows match ``work_apps`` exactly as flow_week and blocks do
(config ``flow_work_apps``: names trimmed and case-folded, ``title:<text>`` inside the window title).

Per local day in ``tz`` (None = this machine's zone), only days with at least one row:

- ``work_h``: work time in hours (overlapping work rows count once).
- ``switches``: times the foreground went from a work row straight to a non-work row (the next row starts
  less than ``gap_s`` after the work row ends). Several non-work rows in a row are one switch; leaving
  after a longer gap with no row (away, or cut by afk) is not a switch.
- ``switches_per_work_h``: switches over work hours; None on a day with no work time (unknown, not zero).
- ``long_block_share``: the share of work time inside blocks (blocks.focus_blocks: work rows joined over
  gaps shorter than ``gap_s``) that lasted at least ``break_after_s`` (config ``break_after_min``, default
  ninety minutes); 0.0 when there was work and no long block, None with no work time. A block is cut at
  the day's edge.
- ``returns`` and ``median_return_s``: for each switch, the seconds from the first non-work row to the next
  work row, counted only when the activity between them has no hole of ``gap_s`` or more (a hole is a
  break away from the device, not a switch) and the return is on the same day. The median of those; None
  when there was none (unknown, not zero).

No work apps configured, or no rows at all, is unknown (None), never zero. Pure: nothing here reads the
clock, a file or the config. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from statistics import median
from typing import Iterable, Optional

from . import blocks as _blocks
from . import flow_week

H = 3600.0


def _days(lo: float, hi: float, tz: Optional[tzinfo]) -> list:
    """[(iso date, start_s, end_s)] for every local day that [lo, hi) touches."""
    d, last = datetime.fromtimestamp(lo, tz).date(), datetime.fromtimestamp(hi, tz).date()
    out = []
    while d <= last:
        s, e = flow_week._day_start(d, tz), flow_week._day_start(d + timedelta(days=1), tz)
        if e > lo and s < hi:
            out.append((d.isoformat(), s, e))
        d += timedelta(days=1)
    return out


def _joined(work: list, gap_s: float) -> list:
    """Merged work spans joined over gaps shorter than ``gap_s``: the day's blocks (as blocks.focus_blocks)."""
    out = []
    for s, e in work:
        if out and s - out[-1][1] < gap_s:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def _day(spans: list, gap_s: float, break_after_s: float) -> dict:
    """The metrics for one day's clipped spans ``[(s, e, is_work)]``, sorted by start."""
    work = flow_week._merge((s, e) for s, e, w in spans if w)
    work_s = flow_week._total(work)
    switches, backs, away, prev_w, prev_end = 0, [], None, None, None
    for s, e, w in spans:
        joined = prev_end is not None and s - prev_end < gap_s
        if w:
            if away is not None and joined:
                backs.append(s - away)
            away = None
        elif away is None and prev_w and joined:
            switches, away = switches + 1, s
        elif away is not None and not joined:
            away = None                      # a hole: a break away from the device, not a switch return
        prev_w, prev_end = w, e if prev_end is None else max(prev_end, e)
    long = [(s, e) for s, e in _joined(work, gap_s) if e - s >= break_after_s]
    in_long = flow_week._total(flow_week._cut(work, long))
    return {"work_h": work_s / H, "switches": switches,
            "switches_per_work_h": switches / (work_s / H) if work_s > 0 else None,
            "long_block_share": in_long / work_s if work_s > 0 else None,
            "returns": len(backs), "median_return_s": median(backs) if backs else None}


def metrics(rows: Optional[Iterable], work_apps: Iterable, gap_s: float = _blocks.GAP_S, *,
            break_after_s: float = _blocks.BREAK_AFTER_MIN * 60.0, tz: Optional[tzinfo] = None) -> Optional[list]:
    """Per-day metrics, oldest day first; None (unknown) with no work apps or no valid row. Pure."""
    work = flow_week._matcher(work_apps)
    if work is None or rows is None:
        return None
    spans = sorted((x["s"], x["e"], work(x)) for x in map(_blocks._span, rows) if x is not None)
    if not spans:
        return None
    out = []
    for day, ds, de in _days(spans[0][0], max(e for _, e, _ in spans), tz):
        clipped = [(max(s, ds), min(e, de), w) for s, e, w in spans if s < de and e > ds]
        clipped = [x for x in clipped if x[1] > x[0]]
        if clipped:
            out.append(dict(day=day, **_day(clipped, gap_s, break_after_s)))
    return out
