"""Circadian phase in words, anchored on the wake event, never on a clock.

    phase(wake_at, now, sleep_mode_on, posture=None) -> "just_woke" | "day" | "evening" | "asleep" | "unknown"
    resolve(...)  -> {"phase", "source": "posture" | "wake" | "sleep_mode" | None, "at", "why", "posture_ignored"}

- ``asleep`` while Sleep mode is on (live); nothing overrides it.
- No wake event is ``unknown`` ("no wake event yet"), never a guess. So is a wake after ``now`` (clock skew) or
  older than window.MAX_AWAKE_H (missing data, not a long day).
- ``just_woke``: the first ``light_h`` hours after the wake event (config ``phase_light_h``, default LIGHT_H, a
  short span): the part of the day when outdoor light helps set the day. ``light_h`` only sets when the words
  change; it is not a target.
- ``evening``: once the wind-down event (``wind_down_at``: the wind_down event jobs.MIQ fires on, or Glide's
  wind-down nudge) has happened after the wake event; ``day`` otherwise.
- ``posture``: an optional object from a circadian daemon's posture file (config ``posture_file``, env
  ``LIMITLESS_POSTURE``; its schema is not public). Only ``phase`` (a name) and ``at`` (when it was written) are
  read; any other field is ignored. It overrides the wake-based phase only when it is fresher than the wake
  event, not after ``now``, and names a known phase (KNOWN, ``unknown`` excluded; case, spaces and hyphens are
  loose). Anything else is ignored and ``posture_ignored`` says why.

Every rule is a span since an event; there is no time-of-day rule anywhere, and nothing here reads the clock:
``now`` comes from the caller. ``why`` and ``posture_ignored`` are digit-free words. Pure; stdlib only, 3.9+.
"""
from __future__ import annotations

import math
from typing import Optional

from .state_reader import parse_ts
from .window import MAX_AWAKE_H

KNOWN = ("just_woke", "day", "evening", "asleep", "unknown")
LIGHT_H, LIGHT_CONFIG = 1.0, "phase_light_h"
POSTURE_CONFIG, POSTURE_ENV = "posture_file", "LIMITLESS_POSTURE"
NO_WAKE = "no wake event yet"


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def light_hours(v) -> float:
    """``v`` when it is a positive finite number of hours shorter than a waking day, else LIGHT_H."""
    n = _num(v)
    return n if n is not None and 0 < n < MAX_AWAKE_H else LIGHT_H


def _name(v) -> Optional[str]:
    if not isinstance(v, str):
        return None
    w = "_".join(v.strip().lower().replace("-", " ").split())
    return w if w in KNOWN and w != "unknown" else None


def _out(name: str, source: Optional[str], at: Optional[float], why: str, ignored: Optional[str] = None) -> dict:
    return {"phase": name, "source": source, "at": at, "why": why, "posture_ignored": ignored}


def _posture(posture, wake: Optional[float], now: float):
    """(name, at, None) for a posture that may override, else (None, None, why it is ignored)."""
    if not isinstance(posture, dict):
        return None, None, "the posture is not an object"
    name = _name(posture.get("phase"))
    if name is None:
        return None, None, "the posture names something that is not a known phase"
    raw_at = posture.get("at")
    at = None if isinstance(raw_at, bool) else parse_ts(raw_at)
    if at is None or not math.isfinite(at):
        return None, None, "the posture has no readable time"
    if at > now:
        return None, None, "the posture is from after now"
    if wake is not None and at <= wake:
        return None, None, "the posture is older than the wake event"
    if now - at > MAX_AWAKE_H * 3600:
        return None, None, "the posture is too old"
    return name, at, None


def resolve(wake_at, now: float, sleep_mode_on: bool, posture=None, *, wind_down_at=None,
            light_h=LIGHT_H, sleep_at=None) -> dict:
    """The phase at ``now`` with its source, anchor time and digit-free reason; see the module doc."""
    now = float(now)
    wake = _num(wake_at)
    if sleep_mode_on is True:
        return _out("asleep", "sleep_mode", _num(sleep_at), "Sleep mode is on")
    ignored = None
    if posture is not None:
        name, at, ignored = _posture(posture, wake, now)
        if name is not None:
            return _out(name, "posture", at, "from the posture file, fresher than the wake event")
    if wake is None:
        return _out("unknown", None, None, NO_WAKE, ignored)
    since = now - wake
    if since < 0:
        return _out("unknown", None, None, "the wake event is after now", ignored)
    if since > MAX_AWAKE_H * 3600:
        return _out("unknown", None, None, "the last wake event is too old", ignored)
    wd = _num(wind_down_at)
    if wd is not None and wake < wd <= now:
        return _out("evening", "wake", wd, "the wind-down event has happened since the wake event", ignored)
    if since < light_hours(light_h) * 3600:
        return _out("just_woke", "wake", wake, "the first part after the wake event", ignored)
    return _out("day", "wake", wake, "past the first part after the wake event", ignored)


def phase(wake_at, now: float, sleep_mode_on: bool, posture=None, *, wind_down_at=None,
          light_h=LIGHT_H) -> str:
    """One of KNOWN for ``now``: resolve(...)["phase"]."""
    return resolve(wake_at, now, sleep_mode_on, posture, wind_down_at=wind_down_at, light_h=light_h)["phase"]
