"""GlideProvider: the decision window from Glide's attention state (focus blocks, wind-down nudge).

Glide (https://github.com/kvnloo/glide, ``glide/attention.py``) keeps one JSON file,
``<profile>/glide/attention.json``:

    {"block":  {"start": epoch_s, "end": epoch_s, "minutes": int} | null,   # /glide focus start
     "queue":  [{"title", "body", "cls", "at": epoch_s}],                   # asks held by a block
     "resume": {"saved": epoch_s, "night": "YYYY-MM-DD", ...} | null,       # the wind-down nudge
     "nudged": "YYYY-MM-DD" | "",
     "wind_down": {"started": epoch_s, "by": "nudge" | "manual", "ended": epoch_s | null}}  # newer Glide

This module only reads it. The mapping, from Glide's own events:

- a running block (``block.start <= now < block.end``) -> ``peak``, since ``focus_start``,
  ``hold_asks=True`` (Glide holds every non-critical ask until the block ends);
- Glide's explicit wind-down event (``wind_down``, docs/glide-wind-down-event.md), read first: open
  from ``started`` until ``ended`` or ``wind_down_max_s`` after ``started``, whichever is first ->
  ``wind_down``, since ``wind_down``; outside that span -> unknown. A malformed key (not an object,
  ``started`` not a finite number or after ``now``, ``ended`` before ``started``) is ignored;
- with no usable ``wind_down`` key, a wind-down nudge (``resume.saved``) no older than
  ``wind_down_max_s`` -> ``wind_down``, since ``wind_down``;
- anything else (no file, bad JSON, wrong shape, block over, old or future nudge) -> unknown.

Staleness is the file's own timestamps against the ``now`` the caller passes in. This module
never reads the clock and has no time of day in it; without ``now`` the window is unknown.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Callable, Mapping, Optional, Union

from .decision_window import UNKNOWN, WindowState
from .state_reader import config

ENV_KEY, CONFIG_KEY = "LIMITLESS_GLIDE_ATTENTION", "glide_attention"
# A wind-down with no end event yet is history this long after it started, not an open window.
WIND_DOWN_MAX_S = 4 * 3600
WIND_DOWN_KEY = "wind_down"
BY = ("nudge", "manual")   # wind_down.by as Glide writes it; anything else reads as BY_UNKNOWN
BY_UNKNOWN = "unknown"
SOURCE = "glide"

Now = Union[float, int, Callable[[], float], None]


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _finite(v) -> Optional[float]:
    n = _num(v)
    return n if n is not None and math.isfinite(n) else None


def wind_down_event(data, now) -> Optional[dict]:
    """Glide's explicit wind-down event from an attention.json dict, as
    ``{"started": float, "ended": float | None, "by": "nudge" | "manual" | "unknown"}``, or None when the
    key is absent or malformed: not an object, ``started`` not a finite number or after ``now``, or a
    finite ``ended`` before ``started``. ``ended`` that is not a finite number reads as None (still open,
    up to the cap). None without a numeric ``now``. Pure: no clock, no file."""
    now = _finite(now)
    ev = data.get(WIND_DOWN_KEY) if isinstance(data, dict) else None
    if now is None or not isinstance(ev, dict):
        return None
    started = _finite(ev.get("started"))
    if started is None or started > now:
        return None
    ended = _finite(ev.get("ended"))
    if ended is not None and ended < started:
        return None
    by = ev.get("by")
    return {"started": started, "ended": ended, "by": by if isinstance(by, str) and by in BY else BY_UNKNOWN}


def attention(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[dict]:
    """Glide's attention.json as a dict (path as GlideProvider.from_config), or None when it is not
    configured, unreadable or not an object. Read-only; wind_down.line reads its ``nudged`` night."""
    env = os.environ if env is None else env
    path = env.get(ENV_KEY) or config(env, home).get(CONFIG_KEY)
    if not isinstance(path, str) or not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _unknown() -> WindowState:
    return WindowState(cls=UNKNOWN, source=SOURCE, confidence=0.0)


class GlideProvider:
    """A ``WindowProvider`` over Glide's attention.json. Re-reads the file on every call."""

    def __init__(self, path: str, now: Now = None, wind_down_max_s: float = WIND_DOWN_MAX_S):
        self.path = path
        self._now = now
        self.wind_down_max_s = wind_down_max_s

    @classmethod
    def from_config(cls, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
                    now: Now = None, **kw) -> Optional["GlideProvider"]:
        """Path from $LIMITLESS_GLIDE_ATTENTION, else ``glide_attention`` in config.json; None if neither."""
        env = os.environ if env is None else env
        path = env.get(ENV_KEY) or config(env, home).get(CONFIG_KEY)
        return cls(path, now=now, **kw) if isinstance(path, str) and path else None

    def _read_now(self) -> Optional[float]:
        now = self._now() if callable(self._now) else self._now
        return _num(now)

    def _read(self) -> Optional[dict]:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def wind_down_event(self) -> Optional[dict]:
        """The file's explicit wind-down event (module wind_down_event at ``now``), open or closed; None
        when absent, malformed, unreadable or without ``now``. ``by`` tells a nudge from a manual one."""
        now = self._read_now()
        data = self._read() if now is not None else None
        return wind_down_event(data, now) if data is not None else None

    def current(self) -> WindowState:
        now = self._read_now()
        if now is None:
            return _unknown()
        data = self._read()
        if data is None:
            return _unknown()
        block = data.get("block")
        if isinstance(block, dict):
            start, end = _num(block.get("start")), _num(block.get("end"))
            if start is not None and end is not None and start <= now < end:
                return WindowState(cls="peak", since="focus_start", source=SOURCE, hold_asks=True)
        ev = wind_down_event(data, now)
        if ev is not None:
            if (ev["ended"] is None or now < ev["ended"]) and now - ev["started"] <= self.wind_down_max_s:
                return WindowState(cls="wind_down", since="wind_down", source=SOURCE)
            return _unknown()
        resume = data.get("resume")
        if isinstance(resume, dict):
            saved = _num(resume.get("saved"))
            if saved is not None and 0 <= now - saved <= self.wind_down_max_s:
                return WindowState(cls="wind_down", since="wind_down", source=SOURCE)
        return _unknown()
