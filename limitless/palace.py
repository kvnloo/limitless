"""Memory palace: one optional, trough-only offer of a short walk in the person's own memory-palace app.

The plugin never rebuilds the app: it only offers its link. Config ``palace_link`` (a deep link or URL such as
``palace://example``; unset by default) and ``palace_label`` (default "memory palace"). Unset is off,
everywhere, with the one reason NO_LINK. A link rides in a line the person reads, so it is checked as the
breathing link is (wind_down.breathing_link: a scheme, ``://``, printable ASCII, no space, no digit).
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from typing import Mapping, Optional

from . import wind_down as _wind_down

LINK_KEY, LABEL_KEY = "palace_link", "palace_label"
DEFAULT_LABEL = "memory palace"
MAX_LABEL_CHARS = 40
NO_LINK = "no memory palace link set"
OFF, FITS = "off", "fits now"


def link(cfg) -> Optional[str]:
    """The configured link (spaces around it dropped), or None: unset (the default) or not a link that may ride in
    a digit-free line. The check is wind_down.breathing_link's, called, not copied."""
    v = cfg.get(LINK_KEY) if isinstance(cfg, Mapping) else None
    return _wind_down.breathing_link({_wind_down.BREATHING_KEY: v})


def label(cfg) -> str:
    """``palace_label`` when it is short, printable and digit-free; else DEFAULT_LABEL."""
    v = cfg.get(LABEL_KEY) if isinstance(cfg, Mapping) else None
    if not isinstance(v, str):
        return DEFAULT_LABEL
    v = v.strip()
    if not v or len(v) > MAX_LABEL_CHARS or not v.isprintable() or any(c.isdigit() for c in v):
        return DEFAULT_LABEL
    return v


def status(state, cfg) -> tuple:
    """``(word, reason)``: (OFF, NO_LINK) with no link."""
    if link(cfg) is None:
        return OFF, NO_LINK
    return FITS, None


def offer(state, cfg) -> Optional[str]:
    """The one offer line, or None."""
    word, _ = status(state, cfg)
    return None if word != FITS else ""
