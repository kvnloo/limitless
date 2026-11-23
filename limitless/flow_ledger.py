"""Flow ledger: one local day's deep work, honestly. Focus blocks, whether a feed app leaked into each, what landed.

    got = ledger(rows, work_apps, feed_apps, items, day, now, tz=None, gap_s=..., break_after_s=...)
    # {day, blocks: [{start, end, long, leak, apps}] | None, long_blocks, leaks, landed, why}
    word = label(got)        # "two long blocks, one with a feed leak; three items landed"

Wraps what is already there, re-deriving nothing:

- Blocks are blocks.focus_blocks over the day's app-in-foreground rows (config ``flow_work_apps``,
  ``block_gap_min``), cut at the day's edges. A block is ``long`` when it lasted at least ``break_after_min``
  (blocks.break_after_s, default ninety minutes), the same length the break nudge uses.
- ``leak`` is whether a feed app (feeds_evidence.feed_apps, matched as flow_week matches its feed leak) was in
  the foreground at any moment inside the block. No feed apps set is leak None (unknown), never "no leak".
- ``landed`` counts the work queue's done items (overnight.items_for: StateReader.work_items, file name and
  mtime only) whose mtime falls inside the day. A failed item did not land. No queue configured is None.
  Item names never leave this module; only the count does.

Unknown (``blocks`` None, ``why`` a plain digit-free reason) when the day is not over yet at ``now``, no
work apps are set, or there is no app activity row inside the day. A day with activity and no work row is
known: no blocks.

No score, no ranking, no comparison to a target, no advice: the ledger and its words say what the activity
rows show and nothing more. They describe observed app activity, not attention or output. ``label`` has no
digit, no clock time, no app name and no file name. Block start and end seconds and app names are T0: the
tool shows them only under the person's raw opt-in (LIMITLESS_RAW_IN_PROMPT=1).

``ledger`` and ``label`` are pure. ``read_for(reader, day, now, env, home, tz)`` reads every input from config,
read-only. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from datetime import date, timedelta, tzinfo
from pathlib import Path
from typing import Iterable, Mapping, Optional

from . import blocks as _blocks
from . import feeds_evidence, flow_week
from . import overnight as _overnight

NOT_OVER = "the day is not over"
NO_WORK_APPS = "no work apps set (flow_work_apps)"
NO_ACTIVITY = "no app activity that day"
LANDED = "done"          # the work-queue status that counts as landed


def day_bounds(day: date, tz: Optional[tzinfo] = None) -> tuple:
    """``(start_s, end_s)`` of the local day ``day`` in ``tz`` (None = this machine's zone)."""
    return flow_week._day_start(day, tz), flow_week._day_start(day + timedelta(days=1), tz)


def _clip(rows: Iterable, lo: float, hi: float) -> list:
    """The valid rows cut to [lo, hi), as blocks' row shape ``{start, end, names, title}``."""
    out = []
    for x in map(_blocks._span, rows or ()):
        if x is None:
            continue
        s, e = max(x["s"], lo), min(x["e"], hi)
        if e > s:
            out.append({"start": s, "end": e, "names": sorted(x["names"]), "title": x["title"]})
    return out


def landed(items: Optional[list], lo: float, hi: float) -> Optional[int]:
    """Done work-queue items whose mtime is in [lo, hi); None (unknown) when the queue is."""
    if items is None:
        return None
    n = 0
    for r in items:
        mt = r.get("mtime") if isinstance(r, dict) else None
        if (isinstance(r, dict) and r.get("status") == LANDED and isinstance(mt, (int, float))
                and not isinstance(mt, bool) and lo <= mt < hi):
            n += 1
    return n


def _unknown(day: date, why: str, items, lo: float, hi: float) -> dict:
    return {"day": day.isoformat(), "blocks": None, "long_blocks": None, "leaks": None,
            "landed": landed(items, lo, hi), "why": why}


def ledger(rows: Optional[Iterable], work_apps: Iterable, feed_apps: Iterable, items: Optional[list], day: date,
           now: float, tz: Optional[tzinfo] = None, gap_s: float = _blocks.GAP_S,
           break_after_s: float = _blocks.BREAK_AFTER_MIN * 60.0) -> dict:
    """The ledger of one local day. Pure: ``now`` comes from the caller, nothing is read or written."""
    lo, hi = day_bounds(day, tz)
    if now < hi:
        return _unknown(day, NOT_OVER, items, lo, hi)
    if flow_week._matcher(work_apps) is None:
        return _unknown(day, NO_WORK_APPS, items, lo, hi)
    day_rows = None if rows is None else _clip(rows, lo, hi)
    if not day_rows:
        return _unknown(day, NO_ACTIVITY, items, lo, hi)
    feed = flow_week._matcher(feed_apps)
    spans = [x for x in map(_blocks._span, day_rows) if x is not None]
    out = []
    for s, e in _blocks.focus_blocks(day_rows, work_apps, gap_s) or ():
        inside = [x for x in spans if x["s"] < e and x["e"] > s]
        out.append({"start": s, "end": e, "long": e - s >= break_after_s,
                    "leak": None if feed is None else any(feed(x) for x in inside),
                    "apps": sorted({n for x in inside for n in x["names"]})})
    longs = [b for b in out if b["long"]]
    return {"day": day.isoformat(), "blocks": out, "long_blocks": len(longs),
            "leaks": None if feed is None else sum(1 for b in longs if b["leak"]),
            "landed": landed(items, lo, hi), "why": ""}


# --- words: the T1 label (digit-free, no clock time, no app or file name) --------------------------------

TIER, MODALITY = "T1", "observed"     # observed app activity, not attention or output
UNKNOWN = "unknown"
NO_LONG = "no long blocks"
_WORDS = ("none", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
SEVERAL = "several"                   # above ten: the words stay digit-free and coarse


def number_word(n: int) -> str:
    """none, one ... ten, then several."""
    return _WORDS[n] if 0 <= n < len(_WORDS) else SEVERAL if n >= len(_WORDS) else _WORDS[0]


def _leak_words(n: int, k: Optional[int]) -> str:
    if k is None:
        return "feed leaks unknown"
    if k <= 0:
        return "no feed leak" if n == 1 else "none with a feed leak"
    if k >= n:
        return "with a feed leak" if n == 1 else "both with a feed leak" if n == 2 else "all with a feed leak"
    return f"{number_word(k)} with a feed leak"


def _landed_words(n: Optional[int]) -> str:
    if n is None:
        return ""
    if n <= 0:
        return "nothing landed"
    return f"{number_word(n)} {'item' if n == 1 else 'items'} landed"


def label(got: Optional[dict]) -> str:
    """The ledger in words: "two long blocks, one with a feed leak; three items landed", "no long blocks",
    or "unknown: <why>". The landed part only when the work queue is known. Pure, digit-free."""
    if not isinstance(got, dict):
        return UNKNOWN
    if got.get("blocks") is None:
        return f"{UNKNOWN}: {got['why']}" if got.get("why") else UNKNOWN
    n = got.get("long_blocks") or 0
    words = NO_LONG if n <= 0 else (f"{number_word(n)} long {'block' if n == 1 else 'blocks'}, "
                                    f"{_leak_words(n, got.get('leaks'))}")
    tail = _landed_words(got.get("landed"))
    return f"{words}; {tail}" if tail else words


def t1(got: Optional[dict]) -> dict:
    """label() as a T1 label dict."""
    return {"label": label(got), "tier": TIER, "modality": MODALITY}


# --- config: every input for one day, read-only ---------------------------------------------------------


def read_for(reader, day: date, now: float, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
             tz: Optional[tzinfo] = None) -> dict:
    """ledger() for ``day`` with every input from config: the ActivityWatch DB (blocks.read_rows, read-only,
    cut to not-afk spans), ``flow_work_apps``, ``feed_apps``, ``block_gap_min``, ``break_after_min`` and the
    work queue (overnight.items_for). Adds ``rows_end``: the newest activity moment inside the day (None when
    unknown). No readable DB says so in ``why``. Never writes."""
    lo, hi = day_bounds(day, tz)
    db = reader.aw_db_path(env, home)
    rows = None if db is None else _blocks.read_rows(db, lo, hi)
    got = ledger(rows, flow_week.work_apps(env, home), feeds_evidence.feed_apps(env, home),
                 _overnight.items_for(reader, env, home), day, now, tz,
                 _blocks.gap_s(env, home), _blocks.break_after_s(env, home))
    if got["why"] == NO_ACTIVITY and rows is None:
        got["why"] = _blocks.NO_DB
    day_rows = _clip(rows, lo, hi) if got["blocks"] is not None else []
    got["rows_end"] = max((r["end"] for r in day_rows), default=None)
    return got
