"""Anki reviews, measured from Anki's own review log and read only: how many reviews happened this week.

    got = reviews(db_path, since_s, until_s)
    # {"count": int|None, "newest_s": float|None, "stamps_s": [epoch s, ...], "reason": str|None}

The collection is an Anki ``collection.anki2`` (SQLite). ``revlog`` has one row per answer, its ``id`` the
answer's time in epoch milliseconds. A review is a row in ``[since_s, until_s)`` whose ``ease`` is not 0 (an
ease of 0 is a manual reschedule such as "set due date", not an answer). ``newest_s`` is the newest review
before ``until_s`` in the whole log, so a week with no review still has an age.

Read-only, always: the file is opened through a ``file:...?mode=ro`` URI, plus ``immutable=1`` when the file
is a copy (config ``anki_copy: true``, e.g. a synced or exported copy no Anki process has open) or a closed
WAL-mode file (no ``-wal`` beside it: a plain read-only open would leave ``-wal``/``-shm`` files). Nothing here
writes, creates or locks the collection. A missing path, a missing file, a locked DB (Anki is syncing) or a
file that is not a collection is unknown: ``count`` None with a reason that never names the path. Unknown is
never zero, and nothing here raises.

Week, in words (``week(db_path, first, today, tz)``): the days from ``first`` to ``today`` (at most seven) are
the days so far; a day with a review is a local day (in ``tz``) with at least one. The T1 label, digit-free:

- "no reviews this week": the week so far has no review (a known none, not a failure);
- "reviewed most days this week": more than half of the days so far had a review;
- "some reviews this week": anything in between; "unknown" when the count is unknown.

These are wording, not targets: nothing here says how many reviews are enough, keeps a streak or marks a
day missed. A day with no review is unlogged.

Trough offer (``offer(window_state, week)``): the one digit-free line "trough: a short Anki review fits now",
only when a trough job would deliver now (decision_window.decide for a ``trough`` job: a trough window is open,
not asleep, no focus block holding asks) and a collection is set. Never in a peak, asleep, an unknown window or
a focus block; never by clock time. It changes what the agent sees, nothing more: nothing here sends.

Where: $LIMITLESS_ANKI, else config ``anki_collection``; none by default (then "no Anki collection set").
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import math
import os
import sqlite3
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import quote

from . import decision_window, jobs
from .state_reader import config

ENV_KEY, CONFIG_KEY, COPY_CONFIG = "LIMITLESS_ANKI", "anki_collection", "anki_copy"
MODALITY = "measured"
BUSY_TIMEOUT_S = 0.5     # Anki syncing holds the file locked; read as unknown rather than wait

NO_COLLECTION = "no Anki collection set"
NO_FILE = "no Anki collection at the configured path"
LOCKED = "the Anki collection is locked (Anki may be syncing): unknown, not zero"
NOT_ANKI = "the Anki collection could not be read (broken or not an Anki collection)"
BAD_RANGE = "no valid time range"

_ROWS = "SELECT id FROM revlog WHERE typeof(id) = 'integer' AND id >= ? AND id < ? AND ease != 0 ORDER BY id"
_NEWEST = "SELECT MAX(id) FROM revlog WHERE typeof(id) = 'integer' AND id < ? AND ease != 0"


def collection_path(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[Path]:
    """$LIMITLESS_ANKI, else config ``anki_collection``; a leading ``~/`` is the home dir. None when unset."""
    env = os.environ if env is None else env
    v = env.get(ENV_KEY) or config(env, home).get(CONFIG_KEY)
    if not isinstance(v, str) or not v.strip():
        return None
    v = v.strip()
    if home is not None and (v == "~" or v.startswith("~/")):
        return Path(home) / v[2:]
    return Path(v).expanduser()


def is_copy(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> bool:
    """True when config ``anki_copy`` is true: the file is a copy, so it is read with ``immutable=1``."""
    return config(env, home).get(COPY_CONFIG) is True


def _uri(path: Path, immutable: bool) -> str:
    uri = "file:" + quote(str(Path(path).resolve())) + "?mode=ro"
    return uri + "&immutable=1" if immutable else uri


def _quiet_wal(path: Path) -> bool:
    """A WAL-mode file with no ``-wal`` beside it: no process has it open, so nothing can change under a
    reader. A plain ``mode=ro`` open would create (and leave) ``-wal`` and ``-shm`` files next to it, so such
    a file is read with ``immutable=1`` instead: still read-only, and nothing is created."""
    try:
        with open(path, "rb") as f:
            head = f.read(20)
    except OSError:
        return False
    wal = len(head) == 20 and head[:16] == b"SQLite format 3\x00" and head[18] == 2 and head[19] == 2
    return wal and not Path(str(path) + "-wal").exists()


def unknown(reason: str) -> dict:
    return {"count": None, "newest_s": None, "stamps_s": [], "reason": reason}


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def reviews(db_path, since_s, until_s, *, immutable: bool = False, timeout_s: float = BUSY_TIMEOUT_S) -> dict:
    """The reviews in ``[since_s, until_s)`` (epoch seconds) in the collection at ``db_path``. Never raises."""
    if db_path is None or (isinstance(db_path, str) and not db_path.strip()):
        return unknown(NO_COLLECTION)
    lo, hi = _num(since_s), _num(until_s)
    if lo is None or hi is None or hi < lo:
        return unknown(BAD_RANGE)
    try:
        path = Path(db_path)
        if not path.is_file():
            return unknown(NO_FILE)
        con = sqlite3.connect(_uri(path, immutable or _quiet_wal(path)), uri=True, timeout=timeout_s)
        try:
            ids = [r[0] for r in con.execute(_ROWS, (int(lo * 1000), int(hi * 1000))).fetchall()]
            newest = con.execute(_NEWEST, (int(hi * 1000),)).fetchone()[0]
        finally:
            con.close()
    except sqlite3.OperationalError as e:
        return unknown(LOCKED if "locked" in str(e) or "busy" in str(e) else NOT_ANKI)
    except (sqlite3.Error, OSError, ValueError, OverflowError, TypeError):
        return unknown(NOT_ANKI)
    return {"count": len(ids), "newest_s": None if newest is None else newest / 1000,
            "stamps_s": [i / 1000 for i in ids], "reason": None}


# --- the week, in words -----------------------------------------------------------------------------------

WEEK_DAYS = 7
UNKNOWN = "unknown"
NONE, SOME, MOST = "no reviews this week", "some reviews this week", "reviewed most days this week"
LABELS = (UNKNOWN, NONE, SOME, MOST)


def t1(word: str) -> dict:
    return {"label": word, "tier": "T1", "modality": MODALITY}


def _day_start(d: date, tz: Optional[tzinfo]) -> float:
    return datetime.combine(d, time(), tzinfo=tz).timestamp()


def _word(count: int, days_with: int, days_so_far: int) -> str:
    if count == 0:
        return NONE
    return MOST if days_with * 2 > days_so_far else SOME


def week(db_path, first: date, today: date, tz: Optional[tzinfo] = None, *, immutable: bool = False) -> dict:
    """This week's reviews: ``{set, count, days_with_review, days_so_far, newest_s, label, reason}``.

    ``set`` is whether a collection is configured at all (``db_path`` given). Unknown (no collection, an
    unreadable one, ``today`` before ``first``) has ``count`` and the day counts None and label "unknown",
    with the reason. Never raises."""
    out = {"set": db_path is not None and not (isinstance(db_path, str) and not db_path.strip()),
           "count": None, "days_with_review": None, "days_so_far": None, "newest_s": None,
           "label": t1(UNKNOWN), "reason": None}
    if not isinstance(first, date) or not isinstance(today, date) or today < first:
        out["reason"] = BAD_RANGE if out["set"] else NO_COLLECTION
        return out
    last = min(today, first + timedelta(days=WEEK_DAYS - 1))
    try:
        lo, hi = _day_start(first, tz), _day_start(last + timedelta(days=1), tz)
    except (OverflowError, ValueError, OSError):
        out["reason"] = BAD_RANGE
        return out
    got = reviews(db_path, lo, hi, immutable=immutable)
    out["newest_s"] = got["newest_s"]
    if got["count"] is None:
        out["reason"] = got["reason"]
        return out
    days = {datetime.fromtimestamp(s, tz).date() for s in got["stamps_s"]}
    so_far = (last - first).days + 1
    out.update(count=got["count"], days_with_review=len(days), days_so_far=so_far,
               label=t1(_word(got["count"], len(days), so_far)))
    return out


def week_first(habit: Optional[dict], today: date) -> date:
    """The first day of "this week": the running habit week's ``week_of`` when ``today`` is one of its seven
    days, else the seven days ending ``today``."""
    try:
        start = date.fromisoformat(str((habit or {}).get("week_of"))) if isinstance(habit, dict) else None
    except ValueError:
        start = None
    if start is not None and start <= today < start + timedelta(days=WEEK_DAYS):
        return start
    return today - timedelta(days=WEEK_DAYS - 1)


def for_week(first: date, today: date, tz: Optional[tzinfo] = None, env: Optional[Mapping[str, str]] = None,
             home: Optional[Path] = None) -> dict:
    """week() over the configured collection (collection_path, is_copy). Read-only."""
    return week(collection_path(env, home), first, today, tz, immutable=is_copy(env, home))


def review_line(w) -> str:
    """The week review's Anki line, words only: "Anki: some reviews this week (measured)"; "" when the week
    is unknown (no collection set, unreadable) or the label is not one of the known words."""
    lab = w.get("label") if isinstance(w, dict) else None
    word = lab.get("label") if isinstance(lab, dict) else None
    if word not in (NONE, SOME, MOST):
        return ""
    return f"Anki: {word} ({MODALITY})"


# --- the trough offer ---------------------------------------------------------------------------------------

OFFER = "trough: a short Anki review fits now"


def offer(window_state, week) -> str:
    """OFFER when a trough job would deliver in ``window_state`` (a decision_window.WindowState, a window.py
    envelope or a ``{"cls"}`` dict) and ``week`` says a collection is set (``week["set"] is True``); else "".
    Pure: reads no clock, no file."""
    if not isinstance(week, dict) or week.get("set") is not True:
        return ""
    if not isinstance(window_state, (decision_window.WindowState, dict)):
        return ""
    state, asleep = jobs._window(window_state)
    d = decision_window.decide("trough", state, budget_left=1, asleep=asleep)
    return OFFER if d.action == decision_window.DELIVER else ""
