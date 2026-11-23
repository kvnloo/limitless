"""Did the phone see a feed app in the first hour after a wake? A hint for the habit check-in, never an answer.

    feeds_in_first_hour(app_starts, wake_at, feed_apps) -> {"seen": True | False | None, "count": int}

``app_starts`` are ``{"ts", "app", "package"}`` rows (aw_reader.app_starts: app-in-foreground span starts
from an ActivityWatch-for-Android DB copy). The hour is [wake_at, wake_at + jobs.HABIT_CUE_AFTER_S), a
duration from the wake event; nothing here reads a time of day. A start counts when its ``app`` or
``package``, trimmed and case-folded, is in ``feed_apps``.

Missing data is unknown, never clean: ``seen`` is None when there is no wake, no feed list, no rows, or
the newest row is older than the hour's end (the phone data stops inside the hour). The feed list is
the person's own: env LIMITLESS_FEED_APPS (comma list), else config key ``feed_apps`` (a list or a comma
string). The repo ships no list of app names, so with none set every hint is unknown.

The hint is a proxy (an app opened is not a feed read) and it only suggests: Done / No / Skip stays the
person's tap, and nothing here writes habit.json or sends. ``line()`` is the check-in's one plain line;
it has no count, time or app name (labels only, privacy tier T1). Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Mapping, Optional

from . import aw_reader, jobs
from .state_reader import StateReader, config
from .wake_proxy import _ts_s

ENV_KEY = "LIMITLESS_FEED_APPS"
CONFIG_KEY = "feed_apps"
SEEN, NOT_SEEN, UNKNOWN = "seen", "not seen", "unknown"
EVIDENCE_TIER = "proxy"     # an app opened is not a feed read: the hint is a proxy, never an answer
_LINE = {SEEN: "Phone: a feed app was opened in that hour", NOT_SEEN: "Phone: no feed app seen in that hour"}


def _clean(items: Iterable) -> tuple:
    out = []
    for v in items or ():
        w = v.strip() if isinstance(v, str) else ""
        if w and w not in out:
            out.append(w)
    return tuple(out)


def feed_apps(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> tuple:
    """The person's feed apps: $LIMITLESS_FEED_APPS (comma list), else config ``feed_apps``; () when unset."""
    env = os.environ if env is None else env
    v = env.get(ENV_KEY)
    if not (isinstance(v, str) and v.strip()):
        v = config(env, home).get(CONFIG_KEY)
    if isinstance(v, str):
        v = v.split(",")
    return _clean(v) if isinstance(v, (list, tuple)) else ()


def feeds_in_first_hour(app_starts, wake_at, feed_apps) -> dict:
    """``{"seen", "count"}`` for feed-app starts in the hour after ``wake_at``; seen None when unknown."""
    feeds = {w.casefold() for w in _clean(feed_apps)}
    times = []
    for r in app_starts or ():
        t = _ts_s(r)
        if t is not None:
            names = {r.get(k).strip().casefold() for k in ("app", "package") if isinstance(r.get(k), str)}
            times.append((t, bool(names & feeds)))
    if not feeds or isinstance(wake_at, bool) or not isinstance(wake_at, (int, float)):
        return {"seen": None, "count": 0}
    end = float(wake_at) + jobs.HABIT_CUE_AFTER_S
    count = sum(1 for t, feed in times if feed and wake_at <= t < end)
    if not times or max(t for t, _ in times) < end:
        return {"seen": None, "count": count}
    return {"seen": count > 0, "count": count}


def hint(result: Optional[dict]) -> str:
    """seen | not seen | unknown, from a feeds_in_first_hour result."""
    seen = (result or {}).get("seen") if isinstance(result, dict) else None
    return UNKNOWN if seen is None else SEEN if seen else NOT_SEEN


def line(result: Optional[dict]) -> str:
    """The check-in's one plain line, or "" when unknown. No counts, times or app names."""
    return _LINE.get(hint(result), "")


def phone_hint(reader: StateReader, wake_at, env: Optional[Mapping[str, str]] = None,
               home: Optional[Path] = None) -> dict:
    """feeds_in_first_hour for ``wake_at`` from the configured AW DB and feed list (read-only)."""
    feeds = feed_apps(env, home)
    if not feeds or isinstance(wake_at, bool) or not isinstance(wake_at, (int, float)):
        return {"seen": None, "count": 0}
    return feeds_in_first_hour(aw_reader.app_starts(reader.aw_db_path(env, home), since_s=wake_at),
                               wake_at, feeds)
