"""Wind-down line: one gentle suggestion inside the MIQ push, never a push of its own.

    line(cfg, glide_state, night=None) -> "Screens down and lights low when you're ready." | ""

The MIQ question already goes out once per night when the wind-down starts (jobs.MIQ, jobs_runner.body).
This adds at most one short line to that same message: no new job, no second push, no send-gate slot.

- Config ``wind_down_line`` picks one line from the fixed list LINES (any case, surrounding spaces ignored).
  ``"off"`` says nothing. A missing or unknown value is DEFAULT: free text is never sent, so no digit, clock
  time or advice can reach the message through config.
- ``glide_state`` is Glide's attention.json (glide_provider.attention). Glide's wind-down nudge writes
  ``nudged = "<night date>"``; when that equals ``night`` (tonight's night date, jobs_runner.night_date),
  Glide already nudged tonight and this says nothing: one nudge per night across both systems. With no
  ``night`` to compare, any recorded nudge counts (fewer messages is the safe side). No or broken state is
  no nudge. Newer Glide also writes an explicit ``wind_down`` event (glide_provider.wind_down_event); when
  it is well formed at ``now`` and says ``by: "manual"`` (the person ran ``/glide focus wind-down``, which
  sets ``nudged`` too), Glide did not nudge and the line still goes out. A malformed key, an unknown
  ``by`` or no ``now`` keep the ``nudged`` answer above.
- Config ``wind_down_breathing_link`` (off by default): a link to the person's own breathing app, a URL or an
  app deep link such as ``example://breathe``. When set, the same line offers ONE more choice, "slow breathing
  in your app", with the link at the end (docs/breathing-link.md):
  "Screens down and lights low when you're ready, or slow breathing in your app (without heart data): <link>";
  with ``wind_down_line`` off the choice stands alone ("Slow breathing in your app when you're ready (...)").
  The words in brackets say whether live heart data backs it: HEART_LIVE only when the caller says the wearable
  input is fresh (``heart_live``: wearable_live over inputs.json, the rule limitless_status uses, at most
  envelope.STALE_H old), HEART_NONE for stale, down, missing or unknown. A link is one
  token: a scheme, ``://``, at most MAX_LINK_CHARS printable ASCII characters, no space and no digit (a digit
  would make tier_audit.gate drop the whole line); anything else is ignored, never sent. Nothing here opens the
  link, counts breaths or sets a pace: the person's own app does all of that.

Every line is a suggestion ("when you're ready"): no digit, no clock time, no order, no health, supplement or
dosing word. Nothing here dims a screen, switches a mode or sends. Pure: no clock, no file. Stdlib only,
Python 3.9+.
"""
from __future__ import annotations

import re
from typing import Mapping, Optional

from . import glide_provider, mock_guard
from .envelope import STALE_H
from .state_reader import parse_ts

CONFIG_KEY = "wind_down_line"
BREATHING_KEY = "wind_down_breathing_link"
OFF = "off"
DEFAULT = "Screens down and lights low when you're ready."
LINES = (
    DEFAULT,
    "Screens down when you're ready.",
    "Lights low when you're ready.",
)
_BY_WORDS = {ln.lower(): ln for ln in LINES}
CHOICE = "slow breathing in your app"
HEART_LIVE = "with live heart data"
HEART_NONE = "without heart data"
MAX_LINK_CHARS = 200
_LINK = re.compile(r"[A-Za-z][A-Za-z+.-]*://[!-~]+")


def choice(cfg: Optional[Mapping]) -> str:
    """The configured line, ``""`` for off, DEFAULT for anything missing or not in LINES."""
    v = cfg.get(CONFIG_KEY) if isinstance(cfg, Mapping) else None
    if not isinstance(v, str):
        return DEFAULT
    w = v.strip().lower()
    if w == OFF:
        return ""
    return _BY_WORDS.get(w, DEFAULT)


def breathing_link(cfg: Optional[Mapping]) -> Optional[str]:
    """The configured breathing link (surrounding spaces dropped), or None: absent (the default) or not a link
    that may ride in the line (no scheme, a space, a digit, too long, not printable ASCII)."""
    v = cfg.get(BREATHING_KEY) if isinstance(cfg, Mapping) else None
    if not isinstance(v, str):
        return None
    v = v.strip()
    if len(v) > MAX_LINK_CHARS or not _LINK.fullmatch(v) or any(c.isdigit() for c in v):
        return None
    return v


def breathing_words(heart_live: bool = False) -> str:
    """HEART_LIVE only when ``heart_live`` is True; HEART_NONE otherwise."""
    return HEART_LIVE if heart_live is True else HEART_NONE


WEARABLE_INPUTS_KEY = "wearable_inputs"
WEARABLE_INPUTS = ("wearable",)


def wearable_inputs(cfg: Optional[Mapping]) -> tuple:
    """The inputs.json names that count as the wearable: config ``wearable_inputs`` (a list of names; a host
    whose sync names each device's input), else WEARABLE_INPUTS. Blank and non-text names are ignored."""
    v = cfg.get(WEARABLE_INPUTS_KEY) if isinstance(cfg, Mapping) else None
    names = tuple(n.strip() for n in v if isinstance(n, str) and n.strip()) if isinstance(v, list) else ()
    if not names:
        return WEARABLE_INPUTS
    return tuple(n for n in names if not mock_guard.is_mock(n, cfg))   # demo inputs never count: () when all are


def wearable_age_h(inputs, now: float, names=WEARABLE_INPUTS) -> Optional[float]:
    """The wearable input's age now, as limitless_status computes it (tools.status): the freshest of the
    ``names`` in inputs.json ``ageHours`` plus the snapshot's own age (its ``at``), rounded to a tenth. None
    when every named input is down, missing or not a number, or the snapshot has no readable time."""
    hours = inputs.get("ageHours") if isinstance(inputs, Mapping) else None
    if not isinstance(hours, Mapping):
        return None
    ages = [a for a in (hours.get(n) for n in names or () if not mock_guard.is_mock(n))
            if not isinstance(a, bool) and isinstance(a, (int, float))]
    if not ages:
        return None
    at = parse_ts(inputs.get("at"))
    if at is None or not isinstance(now, (int, float)):
        return None
    return round(min(ages) + max(0.0, now - at) / 3600, 1)


def wearable_live(inputs, now: float, names=WEARABLE_INPUTS) -> bool:
    """True only when a wearable input is recording by limitless_status's rule: at most STALE_H old."""
    age = wearable_age_h(inputs, now, names)
    return age is not None and age <= STALE_H


def glide_nudged(glide_state, night: Optional[str] = None, now: Optional[float] = None) -> bool:
    """True when Glide's attention state records its own wind-down nudge for ``night`` (any night when None).
    A well-formed explicit ``wind_down`` event at ``now`` with ``by: "manual"`` is not a nudge."""
    nudged = glide_state.get("nudged") if isinstance(glide_state, Mapping) else None
    if not isinstance(nudged, str) or not nudged.strip():
        return False
    if night is not None and nudged.strip() != night:
        return False
    ev = glide_provider.wind_down_event(dict(glide_state), now)
    return ev is None or ev["by"] != "manual"


def line(cfg: Optional[Mapping], glide_state=None, night: Optional[str] = None, heart_live: bool = False,
         now: Optional[float] = None) -> str:
    """One short wind-down line for tonight's MIQ body, or ``""`` (off, or Glide already nudged tonight).
    ``heart_live`` (wearable_live) only picks the breathing choice's words; it never adds a number. ``now``
    lets a manual explicit wind-down event count as no nudge (glide_nudged)."""
    if glide_nudged(glide_state, night, now):
        return ""
    base, link = choice(cfg), breathing_link(cfg)
    if link is None:
        return base
    words = breathing_words(heart_live)
    if not base:
        return f"{CHOICE[0].upper()}{CHOICE[1:]} when you're ready ({words}): {link}"
    return f"{base.rstrip('.')}, or {CHOICE} ({words}): {link}"
