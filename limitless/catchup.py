"""Catch-up: after an absence, the first turn gets a short roadmap of what happened, not a wall of text.

    build(reader, now, last_seen) -> {"text", "lines"}

``last_seen`` is the person's newest message to any agent before this turn (``last_seen()``: the owner
session DBs via owner_messages, skipping the last TURN_S seconds so this turn's own message does not count).
The catch-up is used only when ``now - last_seen`` is over ``catchup_after_h`` hours (config.json, default
24). At most MAX_LINES lines, TLDR first, with at most one action ("next: ..."):

    [limitless] catch-up: away for a day or two; next: look at the asks waiting
    inputs not recording: bike, scale        (tools.status)
    habit week: running, today Done         (habit.json, jobs.habit_week_gate)
    while away: messages sent: a few; captures saved: one   (jobs-sent.jsonl, captures.jsonl since last_seen)
    asks waiting: one                        (asks.py: pending rows of the configured queue)

Counts are words (count_word: none, one, a few, many). Unknown is not zero: a missing source (no file, no
queue configured) reads "unknown", never "none". Every digit is masked, so each line is T1, and the hook's
text goes through tier_audit.gate (hook "catchup").

Injected once: the pre_llm_call hook remembers, in memory, the last_seen it injected for and stays quiet
while last_seen is unchanged. A later turn normally sees a short gap anyway, because the first turn's own
message is then the newest one in the session DB. Hermes loads a plugin once per CLI or gateway process, so
the in-memory key is enough; no file is written. (on_session_start cannot carry it: its return is ignored.)
Nothing here writes or sends. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Callable, Mapping, Optional

from . import asks as _asks
from . import jobs, jobs_runner, owner_messages, tier_audit, tools
from .capture import FILE as CAPTURES
from .envelope import envelope, missing
from .state_reader import OWNER_DBS_CONFIG, OWNER_DBS_ENV, StateReader, config, parse_ts, state_dir

MAX_LINES = 5
CONFIG_KEY = "catchup_after_h"
DEFAULT_AFTER_H = 24.0
TURN_S = 120.0   # messages this recent are this turn's own, not the last time the person was seen
HOOK = "catchup"
UNKNOWN = "unknown"
AWAY, NOT_AWAY = "away", "not away"


def count_word(n: Optional[int]) -> str:
    """none | one | a few | many; None (the source is missing) is unknown, never none."""
    if n is None:
        return UNKNOWN
    return "none" if n <= 0 else "one" if n == 1 else "a few" if n < 5 else "many"


def away_word(gap_h: float) -> str:
    if gap_h < 24:
        return "for some hours"
    if gap_h < 72:
        return "for a day or two"
    return "for several days" if gap_h < 168 else "for over a week"


def after_h(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> float:
    """config ``catchup_after_h`` when it is a positive number, else DEFAULT_AFTER_H."""
    v = config(env, home).get(CONFIG_KEY)
    ok = isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
    return float(v) if ok else DEFAULT_AFTER_H


def last_seen(reader: StateReader, now: float, env: Optional[Mapping[str, str]] = None,
              home: Optional[Path] = None) -> Optional[float]:
    """Epoch seconds of the person's newest message before this turn; None when no owner DB is configured
    or none has a message (unknown: no catch-up)."""
    paths = reader.owner_db_paths(env, home)
    if paths is None:
        return None
    return parse_ts(owner_messages.newest_user_message(paths, now, until=now - TURN_S)["at"])


def _since(rows, key: str, since: float, now: float) -> int:
    n = 0
    for r in rows:
        t = parse_ts(r.get(key)) if isinstance(r, dict) else None
        if t is not None and since < t <= now:
            n += 1
    return n


def _count_file(reader: StateReader, name: str, key: str, since: float, now: float) -> Optional[int]:
    """Rows of ``name`` stamped after ``since``; None when the file does not exist."""
    if not (reader.path / name).is_file():
        return None
    return _since(reader._jsonl(name), key, since, now)


def _asks_waiting(env, home) -> Optional[int]:
    path = _asks.queue_path(env, home)
    if path is None or not Path(path).is_file():
        return None
    return len(_asks.pending(_asks.read(path)))


def _inputs(reader: StateReader, now: float):
    """(line, not recording?)"""
    st = tools.status(reader, now)
    if st["value"] is None:
        return "inputs: unknown", False
    v = st["value"]
    if v["not_recording"]:
        return "inputs not recording: " + ", ".join(v["not_recording"]), True
    return ("inputs: some unknown" if v["unknown"] else "inputs: all recording"), False


def _habit(reader: StateReader, now: float, today: date):
    """(line, keep-or-drop open?)"""
    h = reader.habit()
    if h is None:
        return "habit week: unknown", False
    if jobs.habit_decision(h) is not None:
        return f"habit week: closed ({jobs.habit_decision(h)})", False
    gate = jobs.habit_week_gate(h, today)
    if gate is None:
        t = tools.habit(reader, now, today)
        day = (t.get("value") or {}).get("today") if isinstance(t, dict) else None
        return "habit week: running" + (f", today {day}" if day else ""), False
    if gate.reason == jobs.NO_WEEK:
        return "habit week: none started", False
    return "habit week: over, keep or drop not answered", True


def build(reader: StateReader, now: float, last_seen: float, *, env: Optional[Mapping[str, str]] = None,
          home: Optional[Path] = None, today: Optional[date] = None) -> dict:
    """{"text", "lines"}: the catch-up since ``last_seen``; at most MAX_LINES digit-free lines."""
    today = today or date.fromtimestamp(now)
    inputs, inputs_down = _inputs(reader, now)
    habit, habit_open = _habit(reader, now, today)
    sent = _count_file(reader, jobs_runner.SENT_LOG, "t", last_seen, now)
    caps = _count_file(reader, CAPTURES, "at", last_seen, now)
    waiting = _asks_waiting(env, home)
    if waiting:
        action = "next: look at the asks waiting"
    elif inputs_down:
        action = "next: check the inputs not recording"
    elif habit_open:
        action = "next: keep or drop last week's habit"
    else:
        action = "nothing needs you"
    lines = [f"[limitless] catch-up: away {away_word(max(0.0, now - last_seen) / 3600)}; {action}",
             inputs, habit,
             f"while away: messages sent: {count_word(sent)}; captures saved: {count_word(caps)}",
             f"asks waiting: {count_word(waiting)}"][:MAX_LINES]
    lines = [re.sub(r"\d+", "#", ln) for ln in lines]   # T1: never a digit, whatever a name holds
    return {"text": "\n".join(lines), "lines": lines}


def tool(reader: StateReader, now: float, env: Optional[Mapping[str, str]] = None,
         home: Optional[Path] = None) -> dict:
    """limitless_catchup: the catch-up since the person last wrote, whatever the gap, as an envelope
    (modality messages, age_h = hours since last seen) with a T1 label: away | not away."""
    if not reader.exists():
        return missing("the state dir does not exist")
    seen = last_seen(reader, now, env, home)
    if seen is None:
        if reader.owner_db_paths(env, home) is None:
            return missing(f"no owner session DBs: set {OWNER_DBS_ENV} or \"{OWNER_DBS_CONFIG}\" in config.json")
        return missing("no earlier message from the person in the owner session DBs")
    gap_h = max(0.0, now - seen) / 3600
    c = build(reader, now, seen, env=env, home=home)
    if tier_audit.gate("tool:limitless_catchup", c["text"], False, env=env, now=now) is None:
        return missing("the catch-up had a digit: blocked")
    out = envelope({"lines": c["lines"]}, "messages", gap_h)
    out["label"] = {"label": AWAY if gap_h > after_h(env, home) else NOT_AWAY, "tier": "T1", "modality": "messages"}
    return out


def make_pre_llm_call(env: Optional[Mapping[str, str]] = None, clock: Callable[[], float] = time.time,
                      home: Optional[Path] = None):
    """The pre_llm_call hook: {"context": catch-up} on the first turn after a gap over after_h, else None."""
    seen_key = {"last": None}

    def pre_llm_call(**kwargs) -> Optional[dict]:
        try:
            e = os.environ if env is None else env
            reader = StateReader(state_dir(e, home))
            if not reader.exists():
                return None
            now = clock()
            seen = last_seen(reader, now, e, home)
            if seen is None or seen == seen_key["last"] or now - seen <= after_h(e, home) * 3600:
                return None
            seen_key["last"] = seen
            text = tier_audit.gate(HOOK, build(reader, now, seen, env=e, home=home)["text"], False, env=e,
                                   home=home, now=now)
            return None if text is None else {"context": text}
        except Exception:  # noqa: BLE001 - a broken catch-up must never break the turn
            return None

    return pre_llm_call
