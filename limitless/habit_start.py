"""Start this week's one habit: habit.json gets a habit and a ``week_of`` date, only when asked to write.

    r = start_week(state_dir, "Lights down at wind-down", today, write=False)   # says what it would do
    r = start_week(state_dir, "Lights down at wind-down", today, write=True)    # writes habit.json

``jobs.habit_week_gate`` keeps the habit check-in quiet until a week is started; this is the one place
that starts one, after the person said yes. It writes ``{"habit", "week_of": today, "start", "at": <ISO
now>, "checkins": {}}``: ``start`` is the habit's 2-minute first step (``first_step``, else null) and
``at`` the time it was written, the keys ``state_reader`` and ``tools.habit`` already read. The write is
habit_replies' atomic one (a 0600 temp file in the state dir, then a rename).

One habit a week. It refuses, in plain words and writing nothing, when the habit text is empty, when a
week is already running (``habit_week_gate`` is None for the existing file) or when one is set to start
later. A finished week (day eight on, or a week with a Keep or Drop decision, which is finished as of
today), an undated one or an unreadable file is replaced, and the old file is kept next to it as
``habit-<week_of>.json`` (``habit-undated.json``), byte for byte with its decision, never deleted and never
overwritten. Reasons and labels are plain words with no digits. Nothing here sends.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from . import jobs
from .habit_replies import HABIT_FILE, _write_atomic

WOULD_START, STARTED, REFUSED = "would start", "started", "refused"
_EMPTY = "the habit text is empty"
_RUNNING = "a habit week is already running: one habit a week"
_LATER = "a habit week is already set to start later: one habit a week"
_KEPT_TAKEN = "an older habit file for that week is already kept: left as it is"


def _result(action: str, reason: str, habit=None, week_of=None, kept=None) -> dict:
    return {"action": action, "reason": reason, "habit": habit, "week_of": week_of, "kept": kept}


def _existing(path: Path):
    """(raw bytes, parsed dict or None) for habit.json; (None, None) when there is no file."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, None
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        obj = None
    return raw, obj if isinstance(obj, dict) else None


def _week_of(old: Optional[dict]) -> Optional[date]:
    try:
        return date.fromisoformat(str((old or {}).get("week_of")))
    except ValueError:
        return None


def _keep(path: Path, raw: bytes) -> None:
    """Copy the old habit.json byte for byte to ``path``, 0600, failing if that name exists."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())


def start_week(state_dir, habit, today: date, write: bool, now: Optional[float] = None,
               first_step: Optional[str] = None) -> dict:
    """``{action, reason, habit, week_of, kept}``: action is would start, started or refused.

    ``kept`` names the file the old habit.json is (or would be) kept as, else None. ``now`` is the
    write time for ``at`` (default: the clock).
    """
    name = habit.strip() if isinstance(habit, str) else ""
    if not name:
        return _result(REFUSED, _EMPTY)
    state = Path(state_dir)
    path = state / HABIT_FILE
    raw, old = _existing(path)
    kept = None
    if raw is not None:
        if jobs.habit_week_gate(old, today) is None:
            return _result(REFUSED, _RUNNING, name)
        old_start = _week_of(old)
        named = isinstance((old or {}).get("habit"), str) and old["habit"].strip()
        if old_start is not None and old_start > today and named:
            return _result(REFUSED, _LATER, name)
        kept = f"habit-{old_start.isoformat()}.json" if old_start is not None else "habit-undated.json"
        if (state / kept).exists():
            return _result(REFUSED, _KEPT_TAKEN, name)
    week_of = today.isoformat()
    if not write:
        return _result(WOULD_START, "dry run: nothing written", name, week_of, kept)
    if raw is not None:
        _keep(state / kept, raw)
    at = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat(timespec="seconds")
    step = first_step.strip() if isinstance(first_step, str) and first_step.strip() else None
    _write_atomic(path, {"habit": name, "week_of": week_of, "start": step, "at": at, "checkins": {}})
    return _result(STARTED, "habit week started: one habit a week", name, week_of, kept)


def line(r: dict) -> str:
    """One plain line: ``would start: <habit> for the week of <date>``, ``started: ...`` or ``refused: why``."""
    if r["action"] == REFUSED:
        return f"refused: {r['reason']}"
    out = f"{r['action']}: {r['habit']} for the week of {r['week_of']}"
    if r.get("kept"):
        out += f" (the finished week {'is' if r['action'] == STARTED else 'would be'} kept as {r['kept']})"
    return out


def label(r: dict) -> str:
    """A digit-free label for the result: would start this habit week, started ..., or refused: why."""
    if r["action"] == REFUSED:
        return f"refused: {r['reason']}"
    return f"{r['action']} this habit week"
