"""GlideProvider: the decision window from Glide's attention state (focus blocks, wind-down nudge).

Glide (https://github.com/kvnloo/glide, ``glide/attention.py``) keeps one JSON file,
``<profile>/glide/attention.json``:

    {"block":  {"start": epoch_s, "end": epoch_s, "minutes": int} | null,   # /glide focus start
     "queue":  [{"title", "body", "cls", "at": epoch_s}],                   # asks held by a block
     "resume": {"saved": epoch_s, "night": "YYYY-MM-DD", ...} | null,       # the wind-down nudge
     "nudged": "YYYY-MM-DD" | ""}

This module only reads it. The mapping, from Glide's own events:

- a running block (``block.start <= now < block.end``) -> ``peak``, since ``focus_start``,
  ``hold_asks=True`` (Glide holds every non-critical ask until the block ends);
- a wind-down nudge (``resume.saved``) no older than ``wind_down_max_s`` -> ``wind_down``,
  since ``wind_down``;
- anything else (no file, bad JSON, wrong shape, block over, old or future nudge) -> unknown.

Staleness is the file's own timestamps against the ``now`` the caller passes in. This module
never reads the clock and has no time of day in it; without ``now`` the window is unknown.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Mapping, Optional, Union

from .decision_window import UNKNOWN, WindowState
from .state_reader import config

ENV_KEY, CONFIG_KEY = "LIMITLESS_GLIDE_ATTENTION", "glide_attention"
# Glide's wind-down has no end event; a nudge older than this is history, not an open window.
WIND_DOWN_MAX_S = 4 * 3600
SOURCE = "glide"

Now = Union[float, int, Callable[[], float], None]


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


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

    def current(self) -> WindowState:
        now = self._read_now()
        if now is None:
            return _unknown()
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return _unknown()
        if not isinstance(data, dict):
            return _unknown()
        block = data.get("block")
        if isinstance(block, dict):
            start, end = _num(block.get("start")), _num(block.get("end"))
            if start is not None and end is not None and start <= now < end:
                return WindowState(cls="peak", since="focus_start", source=SOURCE, hold_asks=True)
        resume = data.get("resume")
        if isinstance(resume, dict):
            saved = _num(resume.get("saved"))
            if saved is not None and 0 <= now - saved <= self.wind_down_max_s:
                return WindowState(cls="wind_down", since="wind_down", source=SOURCE)
        return _unknown()
