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
  no nudge.
- Config ``wind_down_breathing_link`` (off by default): a link to the person's own breathing app, a URL or an
  app deep link such as ``example://breathe``. When set, the same line offers ONE more choice, "slow breathing
  in your app", with the link at the end (docs/breathing-link.md):
  "Screens down and lights low when you're ready, or slow breathing in your app (without heart data): <link>";
  with ``wind_down_line`` off the choice stands alone ("Slow breathing in your app when you're ready (...)").
  The words in brackets say whether heart data backs it (HEART_NONE here; see breathing_words). A link is one
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


def glide_nudged(glide_state, night: Optional[str] = None) -> bool:
    """True when Glide's attention state records its own wind-down nudge for ``night`` (any night when None)."""
    nudged = glide_state.get("nudged") if isinstance(glide_state, Mapping) else None
    if not isinstance(nudged, str) or not nudged.strip():
        return False
    return night is None or nudged.strip() == night


def line(cfg: Optional[Mapping], glide_state=None, night: Optional[str] = None) -> str:
    """One short wind-down line for tonight's MIQ body, or ``""`` (off, or Glide already nudged tonight)."""
    if glide_nudged(glide_state, night):
        return ""
    base, link = choice(cfg), breathing_link(cfg)
    if link is None:
        return base
    words = breathing_words(False)
    if not base:
        return f"{CHOICE[0].upper()}{CHOICE[1:]} when you're ready ({words}): {link}"
    return f"{base.rstrip('.')}, or {CHOICE} ({words}): {link}"
