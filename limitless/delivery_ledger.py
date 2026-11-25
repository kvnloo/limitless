"""Delivery ledger: one sqlite row per message to one target, and the moves between its states (design draft).

Design note: docs/delivery-ledger.md. Nothing reads or writes this ledger yet: kevin-push and the jobs runner
still use sent.json and held.jsonl.

One table, one row per message, a ``state`` column. A move is one ``UPDATE ... WHERE id = ? AND state = ?``;
when it changes no row the move was not allowed from the row's state and ``IllegalTransition`` is raised. The
budget check and the insert of the ``queued`` row (``reserve``), and the check and the move held -> queued
(``release``), each run in one ``BEGIN IMMEDIATE`` transaction, so two writers cannot both take the last slot.

The budget of a target is the number of its non-bypass rows that hold a slot (``queued``, ``sent``, ``unknown``)
reserved since ``day_start``. The caller names the day start (a local midnight, a wake event): there is no
rolling 24 h and no clock read here; every time is passed in as epoch seconds.

Stdlib only (sqlite3), Python 3.9+.
"""
from __future__ import annotations

import sqlite3
from typing import NamedTuple

DEFAULT_CAP = 6   # send_gate.DAILY_CAP: the same N-a-day budget
WINDOW_CLASSES = ("peak", "anytime", "trough", "bypass")
STATES = ("held", "queued", "sent", "failed", "unknown", "expired")
REASONS = ("cap", "quiet", "sleep", "dedup", "failed")
COUNTED = ("queued", "sent", "unknown")   # the states that hold a budget slot
HOLD_REASONS = ("quiet", "sleep")          # the holds a caller decides; cap and dedup are decided here

SCHEMA = """\
CREATE TABLE IF NOT EXISTS delivery (
    id            INTEGER PRIMARY KEY,
    target        TEXT NOT NULL,   -- platform:chat_id:thread_id
    job_id        TEXT,
    dedup_key     TEXT,
    window_class  TEXT NOT NULL CHECK (window_class IN ('peak', 'anytime', 'trough', 'bypass')),
    state         TEXT NOT NULL CHECK (state IN ('held', 'queued', 'sent', 'failed', 'unknown', 'expired')),
    reason        TEXT CHECK (reason IN ('cap', 'quiet', 'sleep', 'dedup', 'failed')),
    body          TEXT NOT NULL,
    created_at    REAL NOT NULL,
    release_after REAL,
    sent_at       REAL,
    reserved_at   REAL,            -- when the row took its budget slot; set exactly while it holds one
    CHECK ((state IN ('queued', 'sent', 'unknown')) = (reserved_at IS NOT NULL)),
    CHECK (state <> 'held' OR reason IS NOT NULL),
    CHECK (state <> 'sent' OR sent_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS delivery_target_state_created ON delivery (target, state, created_at);
"""

BUDGET_SQL = """\
SELECT COUNT(*) FROM delivery
 WHERE target = ? AND state IN ('queued', 'sent', 'unknown')
   AND window_class <> 'bypass' AND reserved_at >= ?"""


class Reservation(NamedTuple):
    id: int
    state: str            # "queued" or "held"
    reason: "str | None"  # None when queued, else cap | quiet | sleep | dedup


def open_ledger(path, timeout: float = 30.0) -> sqlite3.Connection:
    """A connection to the ledger at ``path`` (created with its schema when missing). Autocommit: every
    transaction here is an explicit ``BEGIN IMMEDIATE``. The caller closes it."""
    conn = sqlite3.connect(str(path), timeout=timeout, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
        conn.executescript(SCHEMA)
    except BaseException:
        conn.close()
        raise
    return conn


def _target_ok(target) -> bool:
    parts = target.split(":", 2) if isinstance(target, str) else []
    return len(parts) == 3 and bool(parts[0]) and bool(parts[1]) and "\n" not in target


def _check_args(target, window_class, day_start, now, cap):
    if not _target_ok(target):
        raise ValueError(f"target is not platform:chat_id:thread_id: {target!r}")
    if window_class not in WINDOW_CLASSES:
        raise ValueError(f"unknown window_class: {window_class!r}")
    if day_start > now:
        raise ValueError("day_start is after now")
    if not isinstance(cap, int) or cap < 1:
        raise ValueError(f"cap must be a positive int: {cap!r}")


def _fits(conn, target, window_class, day_start, cap) -> bool:
    return conn.execute(BUDGET_SQL, (target, day_start)).fetchone()[0] < cap


def used(conn, target: str, day_start: float) -> int:
    """The budget slots ``target`` has used since ``day_start`` (BUDGET_SQL)."""
    return conn.execute(BUDGET_SQL, (target, day_start)).fetchone()[0]


def reserve(conn, target: str, body: str, *, day_start: float, now: float, cap: int = DEFAULT_CAP,
            window_class: str = "anytime", job_id: "str | None" = None, dedup_key: "str | None" = None,
            hold: "str | None" = None, release_after: "float | None" = None) -> Reservation:
    """Insert one row for a message to ``target``: ``queued`` when it may go now (it takes its budget slot at
    once), else ``held`` with its reason. In one BEGIN IMMEDIATE, in this order:

    1. ``hold`` (``quiet`` or ``sleep``, the caller's own check): held with that reason.
    2. the budget has no slot for this class: held, ``cap``.
    3. queued.

    ``release_after`` is stored on a held row for ``due_held``."""
    _check_args(target, window_class, day_start, now, cap)
    if hold is not None and hold not in HOLD_REASONS:
        raise ValueError(f"hold must be one of {HOLD_REASONS}: {hold!r}")
    if not isinstance(body, str):
        raise ValueError("body must be a str")
    conn.execute("BEGIN IMMEDIATE")
    try:
        if hold is not None:
            state, reason = "held", hold
        elif not _fits(conn, target, window_class, day_start, cap):
            state, reason = "held", "cap"
        else:
            state, reason, release_after = "queued", None, None
        cur = conn.execute(
            "INSERT INTO delivery (target, job_id, dedup_key, window_class, state, reason, body, created_at,"
            " release_after, reserved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (target, job_id, dedup_key, window_class, state, reason, body, now, release_after,
             now if state == "queued" else None))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return Reservation(cur.lastrowid, state, reason)
