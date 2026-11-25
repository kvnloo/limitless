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
