"""Focus blocks: the person's deep-work blocks as seen in activity data. No score, no target.

    bs = focus_blocks(rows, work_apps, gap_s)     # [(start_s, end_s)], [] for none, None for unknown
    b = current_block(bs, now, gap_s=GAP_S)       # the block still going at ``now``, else None
    evs = long_block_events(bs, break_after_s)    # one ``long_block`` event per block that ran that long
    rows = read_rows(aw_db, lo, hi)               # app-in-foreground rows from an ActivityWatch DB copy

A row is ``{"start", "end"}`` (epoch seconds) with the app's ``app`` / ``package`` names and ``title`` (or
``names``, a list, as read_rows gives them). A work row is one whose app is in ``work_apps`` (config
``flow_work_apps``, the same list and matching as flow_week: names trimmed and case-folded,
``title:<text>`` inside the window title). A block is a run of work rows; it survives a gap shorter than
``gap_s`` (a quick look at another app, or a moment with no row at all) and ends at the last work row
before a longer one. The gap does count inside the block's span: the block is from its first work row to
its last.

No work apps configured, or no rows at all (no DB), is unknown (None), never "no block". The block that is
still going is the latest one whose last work row is less than ``gap_s`` before ``now``: data that has not
arrived yet is not extrapolated. A ``long_block`` event is at the block's start plus ``break_after_s``, and
only when the rows show the block lasted that long; its ``block_start`` is the once key's block.

Durations, not clock times: nothing here has a time of day, and nothing reads the clock (``now`` comes from
the caller). The DB is read through flow_week's read-only reader (``mode=ro``), cut to the not-afk spans
when the DB has an afk bucket. Nothing here sends or writes. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Mapping, Optional

from . import flow_week
from .state_reader import config

EVENT = "long_block"
BREAK_AFTER_MIN, BREAK_CONFIG = 90, "break_after_min"   # the person's usual long-block length, a duration
GAP_MIN, GAP_CONFIG = 10, "block_gap_min"               # a gap this short does not end a block
GAP_S = GAP_MIN * 60.0
NO_DB = "no readable ActivityWatch DB (aw_db)"
LOOKBACK_S = 24 * 3600.0   # how far back read_for reads: today's blocks, not a history


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _span(r) -> Optional[dict]:
    if not isinstance(r, dict):
        return None
    s, e = _num(r.get("start")), _num(r.get("end"))
    if s is None or e is None or e <= s:
        return None
    raw = r.get("names") if isinstance(r.get("names"), (list, tuple, set)) else (r.get("app"), r.get("package"))
    names = {v.strip().casefold() for v in raw if isinstance(v, str)} - {""}
    title = r["title"].casefold() if isinstance(r.get("title"), str) else ""
    return {"s": s, "e": e, "names": names, "title": title}


def focus_blocks(rows: Optional[Iterable], work_apps: Iterable, gap_s: float = GAP_S) -> Optional[list]:
    """``[(start_s, end_s)]`` oldest first: runs of work rows joined over gaps shorter than ``gap_s``.

    None (unknown) when no work app is configured or ``rows`` is None (no data); [] when the apps are known
    and no row is a work row. Bad rows are skipped. Pure.
    """
    work = flow_week._matcher(work_apps)
    if work is None or rows is None:
        return None
    spans = flow_week._merge((x["s"], x["e"]) for x in map(_span, rows) if x is not None and work(x))
    out = []
    for s, e in spans:
        if out and s - out[-1][1] < gap_s:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def current_block(blocks: Optional[list], now: float, gap_s: float = GAP_S):
    """The block still going at ``now``: the latest one that started by ``now`` and whose last work row is
    less than ``gap_s`` before it. None when there is none or the blocks are unknown."""
    for s, e in reversed(blocks or ()):
        if s <= now:
            return (s, e) if now - e < gap_s else None
    return None


def long_block_events(blocks: Optional[list], break_after_s: float) -> list:
    """One ``{"event": "long_block", "at", "block_start", "block_end"}`` per block that lasted at least
    ``break_after_s``; ``at`` is the moment it reached that length. [] for unknown blocks."""
    return [{"event": EVENT, "at": s + break_after_s, "block_start": s, "block_end": e}
            for s, e in blocks or () if e - s >= break_after_s]


def read_rows(aw_db, lo: float, hi: float) -> Optional[list]:
    """App-in-foreground rows ``{"start", "end", "names", "title"}`` overlapping [lo, hi), cut to it and to
    the not-afk spans when the DB has afk rows. None when there is no DB or it cannot be read."""
    if not aw_db or not Path(aw_db).is_file():
        return None
    try:
        windows, afk_rows = flow_week._read(Path(aw_db), lo, hi)
    except (sqlite3.Error, OSError, ValueError, OverflowError, TypeError):
        return None
    here = flow_week._merge(x for x in afk_rows if x is not None)
    out = []
    for w in windows:
        for s, e in (flow_week._cut([(w["s"], w["e"])], here) if afk_rows else [(w["s"], w["e"])]):
            out.append({"start": s, "end": e, "names": sorted(w["names"]), "title": w["title"]})
    return out


def _minutes(env, home, key: str, default: float) -> float:
    v = _num(config(env, home).get(key))
    return (v if v is not None and v > 0 else default) * 60.0


def break_after_s(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> float:
    """Config ``break_after_min`` (a positive number of minutes; default 90) in seconds."""
    return _minutes(env, home, BREAK_CONFIG, BREAK_AFTER_MIN)


def gap_s(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> float:
    """Config ``block_gap_min`` (a positive number of minutes; default 10) in seconds."""
    return _minutes(env, home, GAP_CONFIG, GAP_MIN)


def read_for(reader, now: float, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> dict:
    """Everything from config: ``{blocks, rows_end, why, break_after_s, gap_s}`` for the LOOKBACK_S up to
    ``now``. ``blocks`` None (unknown) carries ``why``, plain and digit-free. Read-only."""
    after, gap = break_after_s(env, home), gap_s(env, home)
    out = {"blocks": None, "rows_end": None, "why": "", "break_after_s": after, "gap_s": gap}
    db = reader.aw_db_path(env, home)
    apps = flow_week.work_apps(env, home)
    rows = None if db is None else read_rows(db, now - LOOKBACK_S, now)
    if rows is None:
        out["why"] = NO_DB
        return out
    if flow_week._matcher(apps) is None:
        out["why"] = "no work apps set (flow_work_apps)"
        return out
    out["blocks"] = focus_blocks(rows, apps, gap)
    out["rows_end"] = max((r["end"] for r in rows), default=None)
    return out
