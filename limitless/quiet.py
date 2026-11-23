"""Quiet, snooze and off: one reply mutes the pushes, and an event (never a clock time) ends it.

    state = load(state_dir)                            # {"mode", "since"} or None
    held, why = active(state, events, last_seen, now)  # pure
    held, why = check(state_dir, now)                  # load + the events and last message it needs
    write(state_dir, "snoozed", since_ts)              # atomic, mode 0600

``quiet.json`` in the state dir is ``{"mode": "on" | "quiet_tonight" | "snoozed" | "off", "since": ISO UTC}``:

- ``off``: every push is dropped until the person replies ``on``. Nothing else ends it.
- ``quiet_tonight``: dropped until the next ``wake`` event after ``since`` (jobs_runner.events).
- ``snoozed``: dropped until the person writes again: a message newer than ``since`` in any owner source
  (owner_messages: the owner session DBs, beacons and the Hermes DB the replies are read from).
- ``on`` (or no file): the send gate decides as before.

There are no times of day and no durations here. A missing, unreadable or malformed file is ``on``: this
fails open to the existing gate and never mutes silently. ``quiet_tonight`` or ``snoozed`` without a valid
``since`` is ``on`` too, and so is a snooze ``check`` cannot test (no message source configured or none
readable), or a quiet night whose wake events cannot be read. Every ``why`` is plain and digit-free; a held
one starts with ``quiet: ``.

Replies (``ingest``, bin/limitless-quiet-ingest [--db PATH] [--write], the habit_replies CLI shape): the
person's Telegram messages from the Hermes session DB (read-only), after ``read_after`` (the second after
the current ``since``; with no valid file, FIRST_READ_S back, so a first run never acts on an old message).
A whole message, case-insensitive, with spaces and trailing punctuation ignored, is a command: ``quiet``
(off), ``quiet tonight``, ``snooze`` or ``snooze until I write again`` (snoozed), ``on``. Anything else,
including any time or duration ("snooze 2h"), is not a command and changes nothing. The latest command
wins and is written with ``since`` = its reply time (whole seconds, UTC). Dry run unless written. Rows
never echo a reply. Nothing here sends. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional, Tuple

QUIET_FILE = "quiet.json"
ON, TONIGHT, SNOOZED, OFF = "on", "quiet_tonight", "snoozed", "off"
MODES = (ON, TONIGHT, SNOOZED, OFF)
PREFIX = "quiet: "
_LABELS = {ON: "on", OFF: "off", TONIGHT: "quiet tonight", SNOOZED: "snoozed"}

WHY_ON = "on: pushes go through the send gate"
WHY_OFF = PREFIX + "off until you reply on"
WHY_TONIGHT = PREFIX + "quiet tonight, until you wake up"
WHY_SNOOZED = PREFIX + "snoozed until you write again"
WHY_WOKE = "on: quiet tonight ended when you woke up"
WHY_WROTE = "on: the snooze ended when you wrote again"
WHY_NO_SINCE = "on: the quiet file has no valid start, so it does not hold"
WHY_NO_WAKES = "on: the wake events cannot be read, so quiet tonight does not hold"
WHY_NO_SOURCE = ("on: this host cannot see when you write, so the snooze does not hold; "
                 "reply quiet to turn pushes off")


WRITE, WOULD_WRITE, IGNORE, NOTHING = "write", "would write", "ignore", "nothing"
FIRST_READ_S = 24 * 3600   # ingest only: how far back a first run (no quiet.json) reads replies; not a quiet rule
COMMANDS = {"quiet": OFF, "quiet tonight": TONIGHT, "snooze": SNOOZED, "snooze until i write again": SNOOZED,
            "on": ON}


def label(mode) -> str:
    """The plain word for a mode: on, off, quiet tonight or snoozed (anything else is on)."""
    return _LABELS.get(mode, _LABELS[ON])


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _since(state) -> Optional[float]:
    v = state.get("since") if isinstance(state, dict) else None
    if not isinstance(v, str):
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.timestamp() if dt.tzinfo is not None else None


def mode_of(state) -> str:
    """The mode a state names; anything that is not one of MODES is on."""
    return state["mode"] if isinstance(state, dict) and state.get("mode") in MODES else ON


def active(state, events: Iterable, last_seen: Optional[float], now: float) -> Tuple[bool, str]:
    """(held, why) for one push at ``now``. Pure.

    ``events``: ``[{"event", "at": epoch}]`` (jobs_runner.events); only ``wake`` rows after ``since`` and at or
    before ``now`` matter. ``last_seen``: epoch of the person's newest message, or None.
    """
    mode = mode_of(state)
    if mode == ON:
        return False, WHY_ON
    if mode == OFF:
        return True, WHY_OFF
    since = _since(state)
    if since is None:
        return False, WHY_NO_SINCE
    if mode == TONIGHT:
        for e in events or ():
            at = e.get("at") if isinstance(e, dict) else None
            if isinstance(e, dict) and e.get("event") == "wake" and _number(at) and since < at <= now:
                return False, WHY_WOKE
        return True, WHY_TONIGHT
    if _number(last_seen) and last_seen > since:
        return False, WHY_WROTE
    return True, WHY_SNOOZED


def load(state_dir) -> Optional[dict]:
    """quiet.json as a dict, or None when it is missing, unreadable or not an object."""
    try:
        data = json.loads((Path(state_dir) / QUIET_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def iso(t: float) -> str:
    """UTC ISO time in whole seconds (the fraction is cut), the shape owner_messages reports."""
    return datetime.fromtimestamp(int(float(t)), timezone.utc).isoformat(timespec="seconds")


def write(state_dir, mode: str, since_ts: float) -> dict:
    """Write ``{"mode", "since"}`` atomically (temp file in the state dir, mode 0600, then a rename)."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    obj = {"mode": mode, "since": iso(since_ts)}
    d = Path(state_dir)
    fd, tmp = tempfile.mkstemp(prefix=".quiet-", suffix=".tmp", dir=str(d))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, d / QUIET_FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return obj


def _last_seen(state_dir, now: float, env, home) -> Tuple[bool, Optional[float]]:
    """(could see, newest message epoch | None) across the owner DBs, beacons and the replies' Hermes DB."""
    from . import habit_replies, owner_messages
    from .state_reader import StateReader, parse_ts
    reader = StateReader(Path(state_dir))
    dbs = list(reader.owner_db_paths(env, home) or [])
    hermes = habit_replies.hermes_db_path(state_dir, env, home)
    if hermes is not None:
        dbs.append(hermes)
    beacons = list(reader.owner_beacon_paths(env, home) or [])
    if not dbs and not beacons:
        return False, None
    got = owner_messages.newest_user_message(dbs, now, beacons=beacons)
    if not got["sources_read"]:
        return False, None
    return True, parse_ts(got["at"])


def check(state_dir, now: float, env: Optional[Mapping[str, str]] = None,
          home: Optional[Path] = None) -> Tuple[bool, str]:
    """active() for quiet.json in ``state_dir``, reading only what its mode needs. Never raises: any error
    reads as on (fails open to the send gate)."""
    try:
        state = load(state_dir)
        mode = mode_of(state)
        if mode == TONIGHT and _since(state) is not None:
            from . import jobs_runner
            from .state_reader import StateReader
            try:
                evs = jobs_runner.events(StateReader(Path(state_dir)), env, home)
            except Exception:  # noqa: BLE001 - unreadable events end nothing; fail open
                return False, WHY_NO_WAKES
            return active(state, evs, None, now)
        if mode == SNOOZED and _since(state) is not None:
            seen, last = _last_seen(state_dir, now, env, home)
            if not seen:
                return False, WHY_NO_SOURCE
            return active(state, [], last, now)
        return active(state, [], None, now)
    except Exception:  # noqa: BLE001 - a broken quiet check must never mute or crash a push
        return False, WHY_ON


def command(text) -> Optional[str]:
    """The mode a whole reply asks for (COMMANDS), or None when it is not exactly a command."""
    if not isinstance(text, str):
        return None
    words = " ".join(text.split()).lower()
    while words and unicodedata.category(words[-1]).startswith("P"):
        words = words[:-1].rstrip()
    return COMMANDS.get(words)


def read_after(state_dir, now: float) -> float:
    """Epoch seconds after which replies are read: the second after the current ``since``, else FIRST_READ_S
    before ``now``."""
    since = _since(load(state_dir))
    return since + 1 if since is not None else float(now) - FIRST_READ_S


def _row(t, mode, action, reason) -> dict:
    return {"reply_at": None if t is None else iso(t), "mode": mode, "label": None if mode is None else label(mode),
            "action": action, "reason": reason}


def ingest(state_dir, replies: Iterable[Tuple[float, str]], now: float, dry_run: bool = True) -> list:
    """One plain-word row per reply (or one ``nothing`` row): ``{reply_at, mode, label, action, reason}``.
    The latest command after the current ``since`` is written (only when not ``dry_run``)."""
    start = read_after(state_dir, now)
    ok = sorted(((float(t), x) for t, x in (replies or ()) if _number(t)), key=lambda r: r[0])
    if not ok:
        return [_row(None, None, NOTHING, "no new message: quiet stays as it is")]
    rows, last = [], None
    for t, text in ok:
        mode = command(text)
        if int(t) < start:
            rows.append(_row(t, None, IGNORE, "before the current quiet setting"))
        elif t > now:
            rows.append(_row(t, None, IGNORE, "after now"))
        elif mode is None:
            rows.append(_row(t, None, IGNORE, "not quiet, quiet tonight, snooze or on: changes nothing"))
        else:
            if last is not None:
                rows[last] = dict(rows[last], action=IGNORE, reason="a later command wins")
            last = len(rows)
            rows.append(_row(t, mode, WOULD_WRITE if dry_run else WRITE, "the latest command"))
    if last is not None and not dry_run:
        write(state_dir, rows[last]["mode"], ok[last][0])     # one row per reply: same index
    return rows
