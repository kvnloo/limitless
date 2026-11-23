"""A Done / No / Skip reply to the habit check-in, written into habit.json's checkins; a Keep / Drop
reply to the week review, written as the week's decision.

    rows = ingest(state_dir, [(ts, text), ...], now)                  # writes habit.json
    rows = ingest(state_dir, replies, now, dry_run=True)              # says what it would write
    rows = decide(state_dir, replies, now)                            # Keep / Drop: dry run by default
    rows = decide(state_dir, replies, now, dry_run=False)             # writes decision + decided_at
    replies = replies_from_hermes_db(db_path, since_ts)               # the person's Telegram messages

A reply counts only when it comes after the latest habit check-in in ``jobs-sent.jsonl`` (sent at or
before ``now``) and no later than that ask's ``stale_after_s``. Its first word, case-insensitive, with
trailing punctuation or one emoji ignored, maps through ``jobs.HABIT_TAPS``: Done, No or Skipped.
Anything else is ignored: the day stays unlogged, never No. The first real tap in one ask wins, and a
day that already has Done, No or Skipped is never overwritten. The day is the local date of the
check-in send. habit.json is rewritten atomically (a temp file in the state dir, then a rename) with
every other key kept. Rows are plain words and never echo the reply. Nothing here sends.

Keep / Drop (``decide``): a reply counts only after the latest week review in ``jobs-sent.jsonl`` that
belongs to this week (sent on or after its day seven, at or before ``now``) and within DECISION_REPLY_S
of it. Its first word, read as above, must be Keep or Drop. The first one writes ``decision`` (Keep or
Drop) and ``decided_at`` (the reply's ISO time, UTC) into habit.json, atomically, with every other key
kept; a decision already there is never overwritten. No reply or any other reply writes nothing: the
week stays undecided, never a Drop. Dry run by default. The written decision also appends the week's one loop
row to predictions.jsonl (stop_rule.record_loop: habit, prediction, outcome, rule verdict, decision); the
rule's verdict never changes the decision.

The Hermes session store is SQLite, opened read-only (``mode=ro``). Columns used, as in
NousResearch/hermes-agent ``hermes_state.py`` (v2026.4.13) and ``persistence/sqlite/_schema_ddl.py``:
``sessions(id, source)`` and ``messages(session_id, role, content, timestamp)``; ``timestamp`` is epoch
seconds. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unicodedata
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import Iterable, Mapping, Optional, Tuple
from urllib.parse import quote

from . import jobs
from .state_reader import StateReader, config

HABIT_FILE = "habit.json"
ENV_KEY = "LIMITLESS_HERMES_DB"
CONFIG_KEY = "hermes_db"
BUSY_TIMEOUT_S = 0.5          # a DB Hermes holds locked reads as no replies rather than waiting
WRITE, WOULD_WRITE, KEEP, IGNORE, NOTHING = "write", "would write", "keep", "ignore", "nothing"
DECISION_REPLY_S = 24 * 3600   # a Keep / Drop counts for a day after the week review; later it is a guess
_ANSWERS = {c.lower() for c in jobs.HABIT_TAPS.values()}
_MODIFIERS = {"\ufe0f", "\ufe0e", "\u200d"} | {chr(c) for c in range(0x1F3FB, 0x1F400)}

_QUERY = (
    "SELECT m.timestamp, m.content FROM messages m JOIN sessions s ON s.id = m.session_id "
    "WHERE s.source = ? AND m.role = 'user' AND m.timestamp > ? ORDER BY m.timestamp, m.id"
)


def _strip_punct(w: str) -> str:
    while w and unicodedata.category(w[-1]).startswith("P"):
        w = w[:-1]
    return w


def _strip_one_emoji(w: str) -> str:
    while w and w[-1] in _MODIFIERS:
        w = w[:-1]
    if w and unicodedata.category(w[-1]) in ("So", "Sk"):
        w = w[:-1]
    while w and w[-1] in _MODIFIERS:
        w = w[:-1]
    return w


def tap(text) -> Optional[str]:
    """Done | No | Skipped from a reply's first word; None for anything else (stays unlogged)."""
    if not isinstance(text, str) or not text.split():
        return None
    word = _strip_punct(_strip_punct(_strip_one_emoji(_strip_punct(text.split()[0]))))
    return jobs.habit_answer(word) if word.isalpha() else None


def _first_word(text) -> Optional[str]:
    if not isinstance(text, str) or not text.split():
        return None
    word = _strip_punct(_strip_punct(_strip_one_emoji(_strip_punct(text.split()[0]))))
    return word if word.isalpha() else None


def decision(text) -> Optional[str]:
    """Keep | Drop from a reply's first word; None for anything else (the week stays undecided)."""
    word = _first_word(text)
    return jobs.habit_decision({"decision": word}) if word else None


def _latest(sent_log: Iterable, job: str, now: float) -> Optional[float]:
    ts = [r["t"] for r in (sent_log or ()) if isinstance(r, dict) and r.get("job") == job
          and isinstance(r.get("t"), (int, float)) and not isinstance(r.get("t"), bool) and r["t"] <= now]
    return max(ts) if ts else None


def latest_checkin(sent_log: Iterable, now: float) -> Optional[float]:
    """The time of the latest habit check-in really sent at or before ``now``; None when there is none."""
    return _latest(sent_log, jobs.HABIT_CHECKIN.name, now)


def latest_review(sent_log: Iterable, now: float) -> Optional[float]:
    """The time of the latest week review really sent at or before ``now``; None when there is none."""
    return _latest(sent_log, jobs.WEEK_REVIEW.name, now)


def _iso(t: float, tz: Optional[tzinfo]) -> str:
    return datetime.fromtimestamp(t, tz or timezone.utc).isoformat(timespec="seconds")


def _row(at, day, answer, action, reason, tz=None) -> dict:
    return {"reply_at": None if at is None else _iso(at, tz), "day": day, "answer": answer,
            "action": action, "reason": reason}


def _write_atomic(path: Path, obj: dict) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".habit-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def ingest(state_dir, replies: Iterable[Tuple[float, str]], now: float, dry_run: bool = False,
           tz: Optional[tzinfo] = None) -> list:
    """One plain-word row per reply (or one ``nothing`` row): ``{reply_at, day, answer, action, reason}``.

    ``tz`` is the zone for the check-in's local date (default: this machine's local zone).
    """
    state = Path(state_dir)
    reader = StateReader(state)
    habit = reader.habit()
    if not habit or not habit.get("habit"):
        return [_row(None, None, None, NOTHING, "no habit.json with a habit: nothing to log")]
    checkins = habit.get("checkins", {})
    if not isinstance(checkins, dict):
        return [_row(None, None, None, NOTHING, "habit.json checkins is not a table: left as it is")]
    sent = latest_checkin(reader.jobs_sent(), now)
    if sent is None:
        return [_row(None, None, None, NOTHING, "no habit check-in sent yet: no reply to log")]
    day = datetime.fromtimestamp(sent, tz).date().isoformat()
    stale = jobs.habit_checkin(habit).stale_after_s or jobs.HABIT_STALE_S
    ok = [(float(t), x) for t, x in (replies or ()) if isinstance(t, (int, float)) and not isinstance(t, bool)]
    if not ok:
        return [_row(None, day, None, NOTHING, "no reply to the habit check-in yet", tz)]
    prior = checkins.get(day)
    have = prior.strip().capitalize() if isinstance(prior, str) and prior.strip().lower() in _ANSWERS else None
    rows, new = [], None
    for t, text in sorted(ok, key=lambda r: r[0]):
        if t <= sent:
            rows.append(_row(t, day, None, IGNORE, "before the latest habit check-in", tz))
            continue
        if t > sent + stale:
            rows.append(_row(t, day, None, IGNORE, f"after the check-in expired ({stale / 3600:.0f} h)", tz))
            continue
        if t > now:
            rows.append(_row(t, day, None, IGNORE, "after now", tz))
            continue
        answer = tap(text)
        if answer is None:
            rows.append(_row(t, day, None, IGNORE, "not Done, No or Skip: the day stays unlogged", tz))
        elif have is not None:
            why = f"an earlier reply to this check-in says {have}" if new else f"the day already says {have}"
            rows.append(_row(t, day, answer, KEEP, why, tz))
        else:
            have = new = answer
            rows.append(_row(t, day, answer, WOULD_WRITE if dry_run else WRITE, "the first tap after the check-in", tz))
    if new is not None and not dry_run:
        _write_atomic(state / HABIT_FILE, dict(habit, checkins=dict(checkins, **{day: new})))
    return rows


def _drow(at, week_of, answer, action, reason, tz=None) -> dict:
    return {"reply_at": None if at is None else _iso(at, tz), "week_of": week_of, "answer": answer,
            "action": action, "reason": reason}


def decide(state_dir, replies: Iterable[Tuple[float, str]], now: float, dry_run: bool = True,
           tz: Optional[tzinfo] = None) -> list:
    """One plain-word row per reply (or one ``nothing`` row): ``{reply_at, week_of, answer, action, reason}``.

    ``tz`` is the zone for the review's local date (default: this machine's local zone). Dry run unless
    ``dry_run=False``.
    """
    state = Path(state_dir)
    reader = StateReader(state)
    habit = reader.habit()
    if not habit or not habit.get("habit"):
        return [_drow(None, None, None, NOTHING, "no habit.json with a habit: no week to decide")]
    day7 = jobs.review_day(habit)
    if day7 is None:
        return [_drow(None, None, None, NOTHING, "habit.json has no valid week_of: no week to decide")]
    week_of = habit["week_of"]
    sent = latest_review(reader.jobs_sent(), now)
    if sent is None or datetime.fromtimestamp(sent, tz).date() < day7:
        return [_drow(None, week_of, None, NOTHING, "no week review sent for this week yet: no reply to log")]
    ok = [(float(t), x) for t, x in (replies or ()) if isinstance(t, (int, float)) and not isinstance(t, bool)]
    if not ok:
        return [_drow(None, week_of, None, NOTHING, "no reply to the week review yet: the week stays undecided")]
    have, new, new_at, rows = jobs.habit_decision(habit), None, None, []
    for t, text in sorted(ok, key=lambda r: r[0]):
        if t <= sent:
            rows.append(_drow(t, week_of, None, IGNORE, "before the latest week review", tz))
        elif t > sent + DECISION_REPLY_S:
            rows.append(_drow(t, week_of, None, IGNORE,
                              f"after the week review expired ({DECISION_REPLY_S / 3600:.0f} h)", tz))
        elif t > now:
            rows.append(_drow(t, week_of, None, IGNORE, "after now", tz))
        elif (answer := decision(text)) is None:
            rows.append(_drow(t, week_of, None, IGNORE, "not Keep or Drop: the week stays undecided", tz))
        elif have is not None:
            why = f"an earlier reply to this review says {have}" if new else f"the week already says {have}"
            rows.append(_drow(t, week_of, answer, KEEP, why, tz))
        else:
            have = new = answer
            new_at = t
            rows.append(_drow(t, week_of, answer, WOULD_WRITE if dry_run else WRITE,
                              "the first Keep or Drop after the week review", tz))
    if new is not None and not dry_run:
        from . import stop_rule   # not at the top: stop_rule -> prediction -> habit_replies
        decided = dict(habit, decision=new, decided_at=_iso(new_at, timezone.utc))
        _write_atomic(state / HABIT_FILE, decided)
        stop_rule.record_loop(state, decided, new, decided["decided_at"], reader.habit_days(), now)
    return rows


def hermes_db_path(state_dir, env: Optional[Mapping[str, str]] = None,
                   home: Optional[Path] = None, arg: Optional[str] = None) -> Optional[Path]:
    """The Hermes session DB: ``arg`` (--db), else $LIMITLESS_HERMES_DB, else config ``hermes_db``; a
    relative config path is in the state dir. None when none is set (there is no default)."""
    env = os.environ if env is None else env
    if arg:
        return Path(arg).expanduser()
    if env.get(ENV_KEY):
        return Path(env[ENV_KEY]).expanduser()
    v = config(env, home).get(CONFIG_KEY)
    if not isinstance(v, str) or not v:
        return None
    p = Path(v).expanduser()
    return p if p.is_absolute() else Path(state_dir) / p


def replies_from_hermes_db(db_path, since_ts: float, source: str = "telegram") -> list:
    """``[(timestamp, content)]``, oldest first: the person's (role ``user``) messages from ``source``
    sessions after ``since_ts``. Read-only; a missing, locked or malformed DB reads as ``[]``."""
    if not db_path:
        return []
    path = Path(db_path)
    if not path.is_file():
        return []
    uri = "file:" + quote(str(path.resolve())) + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_S)
    except sqlite3.Error:
        return []
    try:
        rows = con.execute(_QUERY, (source, float(since_ts))).fetchall()
    except (sqlite3.Error, ValueError, TypeError, OverflowError):
        return []
    finally:
        con.close()
    return [(float(t), c) for t, c in rows
            if isinstance(t, (int, float)) and not isinstance(t, bool) and isinstance(c, str)]
