"""The weekly target: the one habit week counts toward "most days", never a streak.

    p = progress(checkins, week_start, today, target_days=target_days(env))
    # -> {"done", "logged", "target", "reached", "label"} | None

Done counts toward the target. No, Skip and a day with no answer are not failures: they never reduce
anything, there is no streak and nothing resets. ``done`` is the Done days of the week up to ``today``,
``logged`` is Done + No (the week review's M; skipped and unlogged days stay out), ``target`` the
number of Done days that is "most days" this week, ``reached`` whether ``done`` is there yet.

``habit_target_days`` (config, default DEFAULT_TARGET_DAYS of seven) only changes the words a person
sees ("target reached this week" or "on the way"). It is wording, not a rule: it never holds, drops or
sends anything, never starts or closes a week and never changes a check-in.

The label is T1 and digit-free: "not started" (no Done yet), "on the way", "target reached this week",
or "week closed" from day eight on. No habit week started (no valid ``week_start``, or a ``today``
before it) is unknown: None, never zero. Pure: reads its inputs, writes and sends nothing, reads no
clock. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional

from . import jobs
from .state_reader import config

CONFIG_KEY = "habit_target_days"
WEEK_DAYS = 7
DEFAULT_TARGET_DAYS = 4
NOT_STARTED, ON_THE_WAY, REACHED, CLOSED = "not started", "on the way", "target reached this week", "week closed"
LABELS = (NOT_STARTED, ON_THE_WAY, REACHED, CLOSED)
CHECKIN_REACHED = "Target reached this week."   # the habit check-in's one extra line, once reached
REVIEW_REACHED, REVIEW_ON_THE_WAY = f"habit: {REACHED}", f"habit: {ON_THE_WAY}"   # the week review's line
_DONE, _NO = "done", "no"


def _days(v: Any) -> Optional[int]:
    ok = isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= WEEK_DAYS
    return v if ok else None


def target_days(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> int:
    """Config ``habit_target_days`` (a whole number from one to seven), else DEFAULT_TARGET_DAYS."""
    return _days(config(env, home).get(CONFIG_KEY)) or DEFAULT_TARGET_DAYS


def _start(v: Any) -> Optional[date]:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        return None


def _word(v: Any) -> Optional[str]:
    """done | no for a Done or No answer; anything else (Skip, Skipped, no answer, junk) is neither."""
    w = v.strip().lower() if isinstance(v, str) else None
    return w if w in (_DONE, _NO) else None


def label(word: str, modality: str = "self_report") -> dict:
    return {"label": word, "tier": "T1", "modality": modality}


def progress(checkins: Any, week_start: Any, today: date, target_days: Any = DEFAULT_TARGET_DAYS,
             modality: str = "self_report") -> Optional[dict]:
    """``{done, logged, target, reached, label}`` for the week from ``week_start``; None when no week started.

    ``checkins`` is ``{ISO day: Done | No | Skipped}`` (habit.json's checkins, or each day's answer with the
    sync's verdict folded in, as jobs.habit_day gives it). Only the seven days of the week, up to ``today``,
    are read. ``modality`` is the label's (self_report for taps, proxy when the sync filled a day).
    """
    start = _start(week_start)
    if start is None or not isinstance(today, date) or today < start:
        return None
    last = min(today, start + timedelta(days=WEEK_DAYS - 1))
    table = checkins if isinstance(checkins, Mapping) else {}
    words = [_word(table.get((start + timedelta(days=i)).isoformat())) for i in range((last - start).days + 1)]
    done, no = words.count(_DONE), words.count(_NO)
    target = _days(target_days) or DEFAULT_TARGET_DAYS
    reached = done >= target
    if today >= start + timedelta(days=WEEK_DAYS):
        word = CLOSED
    elif reached:
        word = REACHED
    else:
        word = ON_THE_WAY if done else NOT_STARTED
    return {"done": done, "logged": done + no, "target": target, "reached": reached, "label": label(word, modality)}


def week_days(habit: Optional[dict], synced: Optional[dict] = None) -> dict:
    """``{ISO day: Done | No | Skipped | unlogged}`` for the started week's seven days (jobs.habit_day: a tap
    wins over the sync's verdict); {} when no week is started."""
    start = jobs._week_start(habit)
    if start is None:
        return {}
    days = [(start + timedelta(days=i)).isoformat() for i in range(WEEK_DAYS)]
    return {d: jobs.habit_day(habit, d, synced) for d in days}


def for_habit(habit: Optional[dict], synced: Optional[dict] = None, target_days: Any = DEFAULT_TARGET_DAYS,
              today: Optional[date] = None) -> Optional[dict]:
    """progress() for habit.json's started week; ``today`` defaults to its day seven (the whole week, as the
    check-in and the week review read it). None when no week is started."""
    start = jobs._week_start(habit)
    if start is None:
        return None
    return progress(week_days(habit, synced), start, today or jobs.review_day(habit), target_days)


def checkin_line(p: Optional[dict]) -> str:
    """The habit check-in's extra line: CHECKIN_REACHED once the target is reached, else "" (nothing)."""
    return CHECKIN_REACHED if p and p.get("reached") else ""


def review_line(p: Optional[dict]) -> str:
    """The week review's words-only line under its "N of M logged days" line: REVIEW_REACHED, or
    REVIEW_ON_THE_WAY once there is a Done day; "" with none (that line already says what was logged)."""
    if not p:
        return ""
    if p.get("reached"):
        return REVIEW_REACHED
    return REVIEW_ON_THE_WAY if p.get("done") else ""
