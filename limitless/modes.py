"""Attention modes: brainstorm, pm, copilot or focused change only what the person sees, never what gets done.

    mode = load(state_dir)          # "brainstorm" | "pm" | "copilot" | "focused" | "none"
    save(state_dir, "focused")      # atomic, mode 0600; "off" (or "none") returns to none
    line(mode)                      # the one card line for a mode, or None
    apply(window, mode)             # focused: the window with hold_asks set, as a focus block does
    command("mode focused", state_dir)  # the /limitless slash command: read, set or off; a plain reply

A mode adds one short digit-free line (LINES) at the end of the pre_llm_call card, after the cached card and
before tier_audit.gate, so the line is audited with the card. ``focused`` also holds every non-urgent ask the
way a focus block does (asks.py ``hold_asks``, via tools.asks_view); the other modes change no plan.

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
# one short digit-free line per mode, added last to the pre_llm_call card (presentation only)
LINES = {
    BRAINSTORM: "brainstorm mode: offer options, defer decisions",
    PM: "pm mode: status, blockers, next step",
    COPILOT: "copilot mode: do the step, report the result",
    FOCUSED: "focused mode: answer briefly, hold non-urgent asks",
}


def _word(v):
    return v.strip().lower() if isinstance(v, str) else None


def line(mode):
    """The card line for ``mode``; None for none, off or anything that is not a mode."""
    return LINES.get(_word(mode))


def apply(window, mode):
    """The window the asks plan sees: for ``focused``, the same window with ``hold_asks`` set, exactly what a
    focus block provider (e.g. Glide) gives, so asks.plan holds every non-urgent ask with its focus-block
    reason; no new gate. Asleep stays asleep (it holds anyway). Any other mode returns ``window`` itself."""
    if _word(mode) != FOCUSED:
        return window
    from dataclasses import replace

    from . import decision_window, jobs
    state, asleep = jobs._window(window)
    if asleep:
        return window
    if state is None:
        state = decision_window.WindowState(cls=decision_window.UNKNOWN, source="mode")
    return replace(state, hold_asks=True)


USAGE = "usage: /limitless mode [brainstorm|pm|copilot|focused|off]"
ARGS_HINT = "mode [brainstorm|pm|copilot|focused|off]"
DESCRIPTION = ("Attention mode: brainstorm, pm, copilot or focused changes presentation only (one card line, "
               "reply length; focused also holds non-urgent asks); off returns to none. Never sends.")
AS_USUAL = "the card as usual"
NOT_SET = "mode not set: the state dir cannot be written"


def command(raw_args, state_dir) -> str:
    """The reply to ``/limitless <raw_args>``: ``mode`` reads the mode, ``mode <name>`` sets it, ``mode off``
    returns to none; anything else is USAGE and changes nothing. Digit-free, never names a path, never
    sends; a failed write is NOT_SET."""
    words = raw_args.lower().split() if isinstance(raw_args, str) else []
    if not words or words[0] != "mode" or len(words) > 2:
        return USAGE
    if len(words) == 1:
        mode = load(state_dir)
        return f"mode: {line(mode) or NONE + ' (' + AS_USUAL + ')'}"
    if words[1] not in MODES + (OFF,):
        return USAGE
    try:
        mode = save(state_dir, words[1])
    except (OSError, ValueError):
        return NOT_SET
    return f"mode set: {line(mode)}" if mode != NONE else f"mode off: {AS_USUAL}"


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
