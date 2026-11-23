"""Attention modes: brainstorm, pm, copilot or focused change only what the person sees, never what gets done.

    mode = load(state_dir)          # "brainstorm" | "pm" | "copilot" | "focused" | "none"
    save(state_dir, "focused")      # atomic, mode 0600; "off" (or "none") returns to none

``mode.json`` in the state dir is ``{"mode": <one of MODES or "none">}``. ``none`` (no file) is the behaviour
from before modes existed. A missing, unreadable or malformed file, or an unknown mode, is ``none``: this
fails open and never changes the card silently. Nothing here sends. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

MODE_FILE = "mode.json"
BRAINSTORM, PM, COPILOT, FOCUSED = "brainstorm", "pm", "copilot", "focused"
MODES = (BRAINSTORM, PM, COPILOT, FOCUSED)
NONE, OFF = "none", "off"


def _word(v):
    return v.strip().lower() if isinstance(v, str) else None


def load(state_dir) -> str:
    """The mode in ``mode.json``, or ``none`` when it is missing, unreadable, malformed or unknown."""
    try:
        data = json.loads((Path(state_dir) / MODE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return NONE
    mode = _word(data.get("mode")) if isinstance(data, dict) else None
    return mode if mode in MODES else NONE


def save(state_dir, mode) -> str:
    """Write ``{"mode"}`` atomically (temp file in the state dir, mode 0600, then a rename) and return it.
    ``off`` or ``none`` writes ``none``; anything that is not a mode raises ValueError and writes nothing."""
    word = _word(mode)
    if word in (OFF, NONE):
        word = NONE
    elif word not in MODES:
        raise ValueError(f"mode must be one of {MODES} or off, got {mode!r}")
    d = Path(state_dir)
    fd, tmp = tempfile.mkstemp(prefix=".mode-", suffix=".tmp", dir=str(d))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"mode": word}, f)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, d / MODE_FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return word
