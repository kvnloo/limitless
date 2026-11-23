"""Overnight digest: what is running at wind-down, what landed by the wake brief. Counts only, in words.

The work queue (StateReader.work_items, config ``work_queue_dir``) is read by file name and mtime only.

    plan_line(items)          wind-down (the MIQ job body): "Overnight: a few tasks running, one queued"
    landed_line(items, since) wake brief: "Overnight: a few done, one failed" for done / failed items whose
                              mtime is after ``since`` (the wind-down event); "Overnight: nothing ran"
    since(events, now)        the latest wind_down event at or before ``now``; with none in the last
                              MAX_AWAKE_H, ``now`` minus MAX_AWAKE_H (a duration from the event, no clock time)

Counts are labeler.count_word words (none, one, a few, many), so no line or label has a digit, and item
names never appear: a lane name can carry project words. ``items`` None (no dir configured, or not there)
is unknown, not zero: no line. Nothing here writes or sends; callers add the line to a message that is
already going out.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Mapping, Optional

from .labeler import TIER, count_word
from .state_reader import StateReader, parse_ts
from .window import MAX_AWAKE_H

PREFIX = "Overnight: "
MODALITY = "measured"
FINISHED = ("done", "failed")


def _cut(since) -> Optional[float]:
    if isinstance(since, bool) or not isinstance(since, (int, float)) or not math.isfinite(since):
        return None
    return float(since)


def counts(items: Optional[list], since=None) -> Optional[dict]:
    """``{running, queued, done_since, failed_since}`` from work_items rows; done and failed count only when
    their mtime is after ``since`` (all of them when ``since`` is not a number). None for None."""
    if items is None:
        return None
    cut = _cut(since)
    out = {"running": 0, "queued": 0, "done_since": 0, "failed_since": 0}
    for r in items:
        if not isinstance(r, dict):
            continue
        st, mt = r.get("status"), r.get("mtime")
        if st in ("running", "queued"):
            out[st] += 1
        elif st in FINISHED:
            if cut is not None and (not isinstance(mt, (int, float)) or isinstance(mt, bool) or mt <= cut):
                continue
            out[f"{st}_since"] += 1
    return out


def _plan_words(c: dict) -> str:
    run, queued = c["running"], c["queued"]
    if not run and not queued:
        return "nothing running or queued"
    r = f"{count_word(run)} {'task' if run == 1 else 'tasks'} running" if run else "nothing running"
    q = f"{count_word(queued)} queued" if queued else "nothing queued"
    return f"{r}, {q}"


def _landed_words(c: dict) -> str:
    done, failed, run = c["done_since"], c["failed_since"], c["running"]
    still = f"{count_word(run)} still running" if run else ""
    if not done and not failed:
        return f"nothing finished, {still}" if still else "nothing ran"
    words = f"{count_word(done)} done, {count_word(failed)} failed"
    return f"{words}, {still}" if still else words


def plan_line(items: Optional[list]) -> str:
    """The wind-down line: running and queued counts in words; "" when the queue is unknown."""
    c = counts(items)
    return "" if c is None else PREFIX + _plan_words(c)


def landed_line(items: Optional[list], since=None) -> str:
    """The wake-brief line: done and failed since the wind-down, in words; "" when the queue is unknown."""
    c = counts(items, since)
    return "" if c is None else PREFIX + _landed_words(c)


def label(items: Optional[list], since=None) -> dict:
    """The T1 label for the tool: the plan words and the landed words, digit-free and name-free."""
    c = counts(items, since)
    word = "unknown" if c is None else f"{_plan_words(c)}; {_landed_words(c)}"
    return {"label": word, "tier": TIER, "modality": MODALITY}


def since(events: Optional[list], now: float) -> float:
    """The wind-down time: the latest ``wind_down`` event at or before ``now`` and at most MAX_AWAKE_H old,
    else ``now`` minus MAX_AWAKE_H."""
    floor = now - MAX_AWAKE_H * 3600
    best = None
    for e in events or ():
        at = parse_ts(e.get("at")) if isinstance(e, dict) and e.get("event") == "wind_down" else None
        if at is not None and floor <= at <= now and (best is None or at > best):
            best = at
    return floor if best is None else best


def items_for(reader: StateReader, env: Optional[Mapping[str, str]] = None,
              home: Optional[Path] = None) -> Optional[list]:
    """work_items, or None when no dir is configured or it is not there (unknown, not zero)."""
    d = reader.work_queue_dir(env, home)
    if d is None or not d.is_dir():
        return None
    return reader.work_items(None, env=env, home=home)


def _events(reader: StateReader, env, home) -> list:
    from . import jobs_runner   # jobs_runner imports this module: import at call time
    return jobs_runner.events(reader, env=env, home=home)


def plan_for(state_dir, now: float, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> str:
    """plan_line for the state dir's work queue; "" when it is unknown or cannot be read. Never raises."""
    try:
        return plan_line(items_for(StateReader(Path(state_dir)), env, home))
    except Exception:  # noqa: BLE001 - a broken queue must not stop the wind-down message
        return ""


def landed_for(state_dir, now: float, env: Optional[Mapping[str, str]] = None,
               home: Optional[Path] = None) -> str:
    """landed_line since last night's wind-down event; "" when the queue is unknown or cannot be read."""
    try:
        reader = StateReader(Path(state_dir))
        items = items_for(reader, env, home)
        return "" if items is None else landed_line(items, since(_events(reader, env, home), now))
    except Exception:  # noqa: BLE001 - a broken queue must not stop the wake brief
        return ""
