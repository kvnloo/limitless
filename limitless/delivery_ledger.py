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

DEDUP_SQL = """\
SELECT 1 FROM delivery
 WHERE target = ? AND dedup_key = ? AND state IN ('queued', 'sent', 'unknown')
   AND reserved_at >= ? LIMIT 1"""


class IllegalTransition(ValueError):
    """A move the state diagram does not allow from the row's current state (or the row does not exist)."""


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


def _limit(window_class: str, cap: int) -> "int | None":
    """Slots this class may fill: peak every one, anytime and trough all but the last (peak's reserved
    token), bypass no limit."""
    if window_class == "bypass":
        return None
    return cap if window_class == "peak" else cap - 1


def _fits(conn, target, window_class, day_start, cap) -> bool:
    limit = _limit(window_class, cap)
    return limit is None or conn.execute(BUDGET_SQL, (target, day_start)).fetchone()[0] < limit


def _duplicate(conn, target, dedup_key, day_start) -> bool:
    return dedup_key is not None and conn.execute(DEDUP_SQL, (target, dedup_key, day_start)).fetchone() is not None


def used(conn, target: str, day_start: float) -> int:
    """The budget slots ``target`` has used since ``day_start`` (BUDGET_SQL)."""
    return conn.execute(BUDGET_SQL, (target, day_start)).fetchone()[0]


def reserve(conn, target: str, body: str, *, day_start: float, now: float, cap: int = DEFAULT_CAP,
            window_class: str = "anytime", job_id: "str | None" = None, dedup_key: "str | None" = None,
            hold: "str | None" = None, release_after: "float | None" = None) -> Reservation:
    """Insert one row for a message to ``target``: ``queued`` when it may go now (it takes its budget slot at
    once), else ``held`` with its reason. In one BEGIN IMMEDIATE, in this order:

    1. ``dedup_key`` already queued, sent or unknown for this target since ``day_start``: held, ``dedup``.
    2. ``hold`` (``quiet`` or ``sleep``, the caller's own check): held with that reason.
    3. the budget has no slot for this class: held, ``cap``.
    4. queued.

    ``release_after`` is stored on a held row for ``due_held`` (never on a dedup hold: a duplicate never goes)."""
    _check_args(target, window_class, day_start, now, cap)
    if hold is not None and hold not in HOLD_REASONS:
        raise ValueError(f"hold must be one of {HOLD_REASONS}: {hold!r}")
    if not isinstance(body, str):
        raise ValueError("body must be a str")
    conn.execute("BEGIN IMMEDIATE")
    try:
        if _duplicate(conn, target, dedup_key, day_start):
            state, reason, release_after = "held", "dedup", None
        elif hold is not None:
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


def _state(conn, row_id) -> "str | None":
    row = conn.execute("SELECT state FROM delivery WHERE id = ?", (row_id,)).fetchone()
    return row[0] if row else None


def _move(conn, row_id: int, frm, to: str, sets: str = "", args: tuple = ()) -> None:
    """One ``UPDATE ... WHERE id = ? AND state = ?`` per allowed source state (``frm``: a state or a tuple of
    them), stopping at the first that changes the row; when none does, the move is illegal."""
    for state in ((frm,) if isinstance(frm, str) else frm):
        cur = conn.execute(f"UPDATE delivery SET state = ?{sets} WHERE id = ? AND state = ?",
                           (to, *args, row_id, state))
        if cur.rowcount == 1:
            return
    raise IllegalTransition(f"row {row_id}: {_state(conn, row_id) or 'no such row'} -> {to} is not allowed")


def mark_sent(conn, row_id: int, now: float) -> None:
    """queued or unknown -> sent: the transport said it delivered (from ``unknown``: a slow send confirmed
    after its row was named unknown). The row keeps its slot."""
    _move(conn, row_id, ("queued", "unknown"), "sent", ", sent_at = ?", (now,))


def mark_unknown(conn, row_id: int) -> None:
    """queued -> unknown: the transport may have delivered (a timeout, a crash mid-send). The row keeps its
    slot and is never replayed; it leaves ``unknown`` only on a confirmed answer (``mark_sent``,
    ``mark_failed``)."""
    _move(conn, row_id, "queued", "unknown")


def mark_failed(conn, row_id: int, release_after: "float | None" = None) -> None:
    """queued or unknown -> held, reason ``failed``: the transport said it did not deliver. The slot is freed
    (its ``reserved_at`` is cleared) and the row waits for ``release`` like any other held row."""
    _move(conn, row_id, ("queued", "unknown"), "held",
          ", reason = 'failed', reserved_at = NULL, release_after = ?", (release_after,))


def release(conn, row_id: int, *, day_start: float, now: float, cap: int = DEFAULT_CAP) -> Reservation:
    """held -> queued when the budget has a slot for the row's class (the check and the move in one BEGIN
    IMMEDIATE); else the row stays held with reason ``cap``. A dedup hold, or a row that is not held, raises."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT target, window_class, state, reason FROM delivery WHERE id = ?",
                           (row_id,)).fetchone()
        if row is None or row["state"] != "held" or row["reason"] == "dedup":
            what = "no such row" if row is None else f"{row['state']} ({row['reason']})"
            raise IllegalTransition(f"row {row_id}: {what} -> queued is not allowed")
        _check_args(row["target"], row["window_class"], day_start, now, cap)
        if _fits(conn, row["target"], row["window_class"], day_start, cap):
            _move(conn, row_id, "held", "queued", ", reason = NULL, reserved_at = ?, release_after = NULL", (now,))
            out = Reservation(row_id, "queued", None)
        else:
            _move(conn, row_id, "held", "held", ", reason = 'cap'")
            out = Reservation(row_id, "held", "cap")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return out


def due_held(conn, now: float) -> list:
    """The held rows a periodic pass may try to ``release`` now: ``release_after`` set and passed, oldest first.
    Dedup holds never come due."""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM delivery WHERE state = 'held' AND reason <> 'dedup' AND release_after IS NOT NULL"
        " AND release_after <= ? ORDER BY created_at, id", (now,))]


class LedgerNotEmpty(RuntimeError):
    """``import_legacy`` runs once, into an empty ledger (Cutover is one step, never a merge)."""


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _legacy_key(row: dict) -> "str | None":
    once = row.get("once")
    if isinstance(once, str) and once.strip():
        return "once:" + once.strip()
    k = row.get("k")
    return ("k:" + k) if isinstance(k, str) and k else None


def import_legacy(conn, target: str, sent: list, held_rows: list, *, day_start: float, now: float) -> dict:
    """Cutover import (docs/delivery-ledger.md): ``sent`` (sent.json rows) and ``held_rows`` (held.rows() of
    held.jsonl) become ledger rows for ``target`` in ONE BEGIN IMMEDIATE, into an empty ledger only
    (``LedgerNotEmpty`` otherwise). The caller holds the sent.json.lock flock and stops writing both files after.

    - a sent row reserved since ``day_start``: delivered -> ``sent``; marked pending or unknown -> ``unknown``
      (keeps its slot and dedupe key); older rows are outside the budget day and are skipped;
    - a quiet claim (``"quiet": true``) never counted as a send and is skipped;
    - every held row -> ``held`` reason ``sleep`` (Sleep mode is held.jsonl's only writer), its body the title
      line then the body, whatever its age (a held message is never dropped silently: ``expire_old`` counts it);
    - a row that is not one of these shapes is skipped.

    The dedup key is ``once:<key>`` when the row has one, else ``k:<send_gate key>`` (held.hold_key's form).
    Returns counts {sent, unknown, held, skipped}. No clock is read."""
    if not _target_ok(target):
        raise ValueError(f"target is not platform:chat_id:thread_id: {target!r}")
    if day_start > now:
        raise ValueError("day_start is after now")
    out = {"sent": 0, "unknown": 0, "held": 0, "skipped": 0}
    ins = ("INSERT INTO delivery (target, job_id, dedup_key, window_class, state, reason, body, created_at,"
           " release_after, sent_at, reserved_at) VALUES (?, NULL, ?, 'anytime', ?, ?, ?, ?, NULL, ?, ?)")
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("SELECT 1 FROM delivery LIMIT 1").fetchone() is not None:
            raise LedgerNotEmpty("the ledger already has rows: import runs once, at cutover")
        for row in sent:
            t = row.get("t") if isinstance(row, dict) else None
            if not _num(t) or row.get("quiet") is True or not (day_start <= t <= now):
                out["skipped"] += 1
                continue
            if "pending" in row or row.get("unknown") is True:
                conn.execute(ins, (target, _legacy_key(row), "unknown", None, "", t, None, t))
                out["unknown"] += 1
            else:
                conn.execute(ins, (target, _legacy_key(row), "sent", None, "", t, t, t))
                out["sent"] += 1
        for row in held_rows:
            if not isinstance(row, dict):
                out["skipped"] += 1
                continue
            title, body, at = row.get("title"), row.get("body"), row.get("at")
            if not isinstance(title, str) or not isinstance(body, str) or not _num(at):
                out["skipped"] += 1
                continue
            text = f"{title}\n{body}" if title else body
            conn.execute(ins, (target, _legacy_key(row), "held", "sleep", text, float(at), None, None))
            out["held"] += 1
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return out


def expire_old(conn, now: float, max_age_s: float) -> int:
    """held -> expired for every row held since ``now - max_age_s`` or earlier; returns how many moved, for the
    one count line. No row is ever deleted."""
    if max_age_s < 0:
        raise ValueError("max_age_s must not be negative")
    return conn.execute("UPDATE delivery SET state = 'expired' WHERE state = 'held' AND created_at <= ?",
                        (now - max_age_s,)).rowcount
