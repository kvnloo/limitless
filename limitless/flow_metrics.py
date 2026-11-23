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
  when there was none (unknown, not zero). ``return_s`` lists every one, so days can be pooled.

``pooled(days)`` is the same fields over several days (rates and shares from the summed time; the median
over every return), plus ``days`` and ``work_days``. ``label(m)`` turns one day or a pool into T1 words,
digit-free: "work stayed in long blocks", "work was broken up", "mixed" or "unknown: <why>". The words
describe observed app activity only; they are not a measure of attention, concentration or output.
``review_line(word)`` is the week review's one digit-free line for a known word, "" for unknown.

Thresholds (``thresholds(env, home)``; config keys, documented defaults, wording only and not targets):

- ``flow_long_share`` (0.6): at least this share of work time in long blocks, and at most
  ``flow_calm_switches_per_h`` (4) switches per work hour, reads "work stayed in long blocks".
- ``flow_broken_share`` (0.3): less than this share in long blocks, or more than
  ``flow_busy_switches_per_h`` (8) switches per work hour, reads "work was broken up".
- Anything between reads "mixed".

``read_for(reader, lo, hi, env, home, tz)`` reads every input from config (the ActivityWatch DB through
blocks.read_rows, read-only, cut to not-afk spans; ``flow_work_apps``; ``block_gap_min``;
``break_after_min``) for [lo, hi) and returns ``{days, pool, rows_end, why, thresholds}``; ``days`` None
(unknown) carries ``why``, plain and digit-free. The tool's evidence tier is EVIDENCE_TIER
("observed-activity"): app activity as observed, a proxy, never a measure of attention.

No work apps configured, or no rows at all, is unknown (None), never zero. Pure: nothing here reads the
clock, a file or the config. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from statistics import median
from typing import Iterable, Optional

from . import blocks as _blocks
from . import flow_week
from .state_reader import config

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
            "returns": len(backs), "return_s": sorted(backs),
            "median_return_s": median(backs) if backs else None}


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


def pooled(days: Optional[list]) -> Optional[dict]:
    """The per-day metrics over several days; None (unknown) for None or no day."""
    days = [d for d in days or () if isinstance(d, dict)]
    if not days:
        return None
    work_s = sum(d["work_h"] for d in days) * H
    switches = sum(d["switches"] for d in days)
    in_long = sum(d["long_block_share"] * d["work_h"] * H for d in days if d["long_block_share"] is not None)
    backs = sorted(x for d in days for x in d.get("return_s") or ())
    return {"days": len(days), "work_days": sum(1 for d in days if d["work_h"] > 0), "work_h": work_s / H,
            "switches": switches, "switches_per_work_h": switches / (work_s / H) if work_s > 0 else None,
            "long_block_share": in_long / work_s if work_s > 0 else None, "returns": len(backs),
            "return_s": backs, "median_return_s": median(backs) if backs else None}


# --- words: the T1 label (digit-free) -------------------------------------------------------------------

LONG, BROKEN, MIXED, UNKNOWN = "work stayed in long blocks", "work was broken up", "mixed", "unknown"
LABELS = (LONG, BROKEN, MIXED)
NO_DATA, NO_WORK_TIME = "no activity data", "no work time in the activity data"
DEFAULTS = {"long_share": 0.6, "broken_share": 0.3, "calm_switches_per_h": 4.0, "busy_switches_per_h": 8.0}
_SHARES = ("long_share", "broken_share")


def _unknown(why: str) -> str:
    return f"{UNKNOWN}: {why}"


def label(m, why: str = NO_DATA, th: Optional[dict] = None) -> str:
    """T1 words for one day or a pool (``metrics`` / ``pooled``); ``why`` names the reason when ``m`` is
    unknown. Digit-free. ``th`` defaults to DEFAULTS."""
    th = DEFAULTS if th is None else th
    if not isinstance(m, dict):
        return _unknown(why)
    rate, share = m.get("switches_per_work_h"), m.get("long_block_share")
    if rate is None or share is None:
        return _unknown(NO_WORK_TIME)
    if share < th["broken_share"] or rate > th["busy_switches_per_h"]:
        return BROKEN
    if share >= th["long_share"] and rate <= th["calm_switches_per_h"]:
        return LONG
    return MIXED


REVIEW_LINE = "Work pattern this week (observed app activity, not attention): {}."


def review_line(word) -> str:
    """The week review's one line for a known label word, digit-free; "" when unknown (no line at all)."""
    return REVIEW_LINE.format(word) if word in LABELS else ""


def thresholds(env=None, home=None) -> dict:
    """DEFAULTS with each ``flow_<name>`` from config that is valid: a share above zero and at most one, a
    switch rate above zero. Anything else keeps its default."""
    cfg, out = config(env, home), dict(DEFAULTS)
    for k in DEFAULTS:
        v = cfg.get(f"flow_{k}")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 and (k not in _SHARES or v <= 1):
            out[k] = float(v)
    return out


# --- config: every input for a span of time -------------------------------------------------------------

EVIDENCE_TIER = "observed-activity"
NO_WORK_APPS = "no work apps set (flow_work_apps)"


def read_for(reader, lo: float, hi: float, env=None, home=None, tz: Optional[tzinfo] = None,
             no_rows: str = "no activity rows in that time") -> dict:
    """metrics() and pooled() for [lo, hi) with every input from config. Read-only; never raises on a
    missing or bad DB (that is ``why``)."""
    out = {"days": None, "pool": None, "rows_end": None, "why": "", "thresholds": thresholds(env, home)}
    db = reader.aw_db_path(env, home)
    rows = None if db is None else _blocks.read_rows(db, lo, hi)
    apps = flow_week.work_apps(env, home)
    if rows is None:
        out["why"] = _blocks.NO_DB
    elif flow_week._matcher(apps) is None:
        out["why"] = NO_WORK_APPS
    elif not rows:
        out["why"] = no_rows
    else:
        out["days"] = metrics(rows, apps, _blocks.gap_s(env, home), break_after_s=_blocks.break_after_s(env, home),
                              tz=tz)
        out["pool"] = pooled(out["days"])
        out["rows_end"] = max(r["end"] for r in rows)
        if out["days"] is None:
            out["why"] = no_rows
    return out
