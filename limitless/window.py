"""Decision window from state events: asleep | peak | trough | anytime | unknown.

Inputs are events only: phone Sleep-mode changes (sleepmode.jsonl), the Sleep-mode poll heartbeat
(sleepmode-poll.json) and the last phone unlock. The awake classes are bands of hours since the wake
event (the last Sleep-mode off that follows an on), so the answer never depends on the time of day.
Missing or stale evidence gives "unknown" with a reason, never a fallback guess.
Bands can be set per person in config.json under "window_bands" ({"peak": [from_h, to_h], ...}).
"""
from __future__ import annotations

from typing import Mapping, Optional

from .envelope import envelope
from .state_reader import StateReader, parse_ts

POLL_FRESH_S = 600          # the Sleep-mode poll runs every 2 min; older than this = no live signal
UNLOCK_RECENT_S = 30 * 60   # an unlock this recent shows the person is awake
MAX_AWAKE_H = 20.0          # a wake event older than this is missing data, not a long day
DEFAULT_BANDS = {"peak": (1.5, 6.0), "trough": (6.0, 9.0)}  # hours since wake; else "anytime"
CLASSES = ("asleep", "peak", "trough", "anytime", "unknown")


def _unknown(reason: str, age_h: Optional[float] = None) -> dict:
    env = envelope("unknown", "proxy", age_h)
    env["reason"] = reason
    return env


def _known(cls: str, age_s: float, reason: str) -> dict:
    env = envelope(cls, "proxy", max(0.0, age_s) / 3600)
    env["reason"] = reason
    return env


def _band(hours: float, bands: Mapping) -> str:
    for name in ("peak", "trough"):
        lo, hi = bands.get(name, DEFAULT_BANDS[name])
        if lo <= hours < hi:
            return name
    return "anytime"


def classify(sleep_rows: list, poll: Optional[dict], last_unlock: Optional[dict], *, now: float,
             bands: Optional[Mapping] = None) -> dict:
    bands = bands or DEFAULT_BANDS
    rows = sorted((r for r in sleep_rows if parse_ts(r.get("at")) is not None), key=lambda r: parse_ts(r["at"]))
    if not rows:
        return _unknown("no Sleep-mode events in the state dir")
    last = rows[-1]
    poll_at = parse_ts((poll or {}).get("at"))
    poll_fresh = bool(poll and poll.get("ok")) and poll_at is not None and now - poll_at <= POLL_FRESH_S
    unlock_at = parse_ts((last_unlock or {}).get("at"))
    unlock_recent = unlock_at is not None and 0 <= now - unlock_at <= UNLOCK_RECENT_S
    if poll_fresh and last.get("on"):
        return _known("asleep", now - poll_at, "Sleep mode is on (live poll)")
    if last.get("on"):
        return _unknown("Sleep mode was last on and there is no live poll")
    if not (poll_fresh or unlock_recent):
        return _unknown("no live Sleep-mode poll and no recent unlock")
    evidence_s = now - poll_at if poll_fresh else now - unlock_at
    wake_at = None
    for prev, cur in zip(rows, rows[1:]):
        if prev.get("on") and not cur.get("on"):
            wake_at = parse_ts(cur["at"])
    if wake_at is None:
        return _unknown("awake, but no wake event (Sleep mode off after on)", evidence_s / 3600)
    since_h = (now - wake_at) / 3600
    if since_h > MAX_AWAKE_H:
        return _unknown(f"the last wake event is {since_h:.0f} h old", evidence_s / 3600)
    cls = _band(since_h, bands)
    src = "live poll" if poll_fresh else "recent unlock"
    return _known(cls, evidence_s, f"{since_h:.1f} h since the wake event; awake per {src}")


def window(reader: StateReader, now: float, bands: Optional[Mapping] = None) -> dict:
    return classify(reader.sleepmode(), reader.sleepmode_poll(), reader.last_unlock(), now=now, bands=bands)
