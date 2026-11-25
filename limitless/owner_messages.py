"""When the person last wrote to an agent: the newest ``user`` message across several Hermes session stores.

    out = newest_user_message([db, ...], now, beacons=[path, ...])
          # {"at": iso | None, "age_h": float | None, "sources_read": int, "sources_failed": int}

The person chats from several machines, each with its own Hermes session store, so one store alone can look
a day old while they are active. Every store is read; the newest role ``user`` message wins, from any
session source except the ones Hermes starts by itself (AUTOMATED_SOURCES: cron, kanban, subagent), whose
``user`` rows are the agent's own prompts. Only the timestamp is read: message content is never selected or returned. Each store is
opened read-only (``mode=ro``) with a short busy timeout; a missing, locked or malformed store counts in
``sources_failed`` and never raises. A message stamped more than SKEW_S after ``now`` (a machine whose clock
is wrong) is ignored; a smaller skew reads as age 0. Paths: ``StateReader.owner_db_paths`` ($LIMITLESS_OWNER_DBS or config ``owner_dbs``; none by default).

A machine whose store this host cannot open writes a beacon instead (bin/limitless-owner-beacon): a JSON
object ``{"at": ISO UTC, "v": 1}`` holding only its newest user-message time. Each beacon
(``StateReader.owner_beacon_paths``) is one more source: read when it parses, failed when it is missing,
unreadable, over BEACON_MAX_BYTES, not that shape, has no timezone, or is stamped more than SKEW_S after
``now``. A beacon after the bound (``until``) was read but is ignored, like a newer row in a store. A stale
beacon is only an old timestamp.
Nothing here writes or sends. Stdlib only, Python 3.9+.

Schema, as in NousResearch/hermes-agent ``persistence/sqlite/_schema_ddl.py`` (0f602c5):
``sessions(id, source)``, ``messages(session_id, role, content, timestamp REAL NOT NULL)`` (epoch seconds)
and ``idx_messages_session ON messages(session_id, timestamp)``. Hermes has no index that leads with
``timestamp`` and none on ``role``, so a plain ``ORDER BY timestamp DESC LIMIT 1`` over messages would be a
full scan plus a sort. Instead the read walks ``idx_messages_session`` backwards once per session
(``PER_SESSION_SQL``): its cost is one probe per session plus the trailing non-user rows it steps over in
each session (tool and assistant rows after the person's last message), never every message in the store.
A store with an index leading on ``timestamp`` is read with one ``ORDER BY timestamp DESC LIMIT 1``
(``FLAT_SQL``); a store with neither index gets ``FLAT_SQL`` as a full scan, the only case that reads every row.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote

from .state_reader import OWNER_DBS_CONFIG as CONFIG_KEY, OWNER_DBS_ENV as ENV_KEY  # noqa: F401

BUSY_TIMEOUT_S = 0.5   # a store Hermes holds locked counts as failed rather than holding up the turn
SKEW_S = 300.0         # clock skew between machines tolerated before a timestamp counts as wrong
BEACON_V = 1           # the only beacon shape: {"at": ISO with offset, "v": 1}
BEACON_MAX_BYTES = 4096  # a beacon is a few dozen bytes; anything larger is not one

# Session sources Hermes starts by itself: their role ``user`` rows are the agent's own prompts (a cron
# job's prompt, a kanban card's brief, a delegated child's goal), never the person writing.
AUTOMATED_SOURCES = ("cron", "kanban", "subagent")
_NOT_AUTOMATED = "s.source NOT IN (" + ", ".join("'" + s + "'" for s in AUTOMATED_SOURCES) + ")"
FLAT_SQL = ("SELECT m.timestamp FROM messages m JOIN sessions s ON s.id = m.session_id "
            "WHERE m.role = 'user' AND m.timestamp <= ? AND " + _NOT_AUTOMATED + " "
            "ORDER BY m.timestamp DESC LIMIT 1")
PER_SESSION_SQL = ("SELECT MAX((SELECT m.timestamp FROM messages m WHERE m.session_id = s.id "
                   "AND m.role = 'user' AND m.timestamp <= ? ORDER BY m.timestamp DESC LIMIT 1)) FROM sessions s "
                   "WHERE " + _NOT_AUTOMATED)


def _index_columns(con) -> list:
    """The column lists of the full (non-partial) indexes on messages."""
    out = []
    for row in con.execute("PRAGMA index_list(messages)").fetchall():
        name, partial = row[1], row[4] if len(row) > 4 else 0
        if partial:
            continue
        out.append([r[2] for r in con.execute(f"PRAGMA index_info({_quote_ident(name)})").fetchall()])
    return out


def _quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def query_for(con) -> str:
    """The cheapest query this store's indexes allow (see the module docstring)."""
    cols = _index_columns(con)
    if any(c[:1] == ["timestamp"] for c in cols):
        return FLAT_SQL
    if any(c[:2] == ["session_id", "timestamp"] for c in cols):
        return PER_SESSION_SQL
    return FLAT_SQL


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _newest_in(path, bound: float):
    """(True, ts | None) when the store was read, (False, None) when it could not be. Rows after ``bound``
    (epoch seconds) are ignored."""
    if not path:
        return False, None
    p = Path(path)
    if not p.is_file():
        return False, None
    uri = "file:" + quote(str(p.resolve())) + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_S)
    except sqlite3.Error:
        return False, None
    try:
        row = con.execute(query_for(con), (float(bound),)).fetchone()
    except (sqlite3.Error, ValueError, TypeError, OverflowError):
        return False, None
    finally:
        con.close()
    t = row[0] if row else None
    return True, float(t) if _number(t) else None


def beacon_time(text: str) -> Optional[float]:
    """Epoch seconds from a beacon's text, or None when it is not ``{"at": ISO with offset, "v": 1}``."""
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    if not isinstance(obj, dict) or type(obj.get("v")) is not int or obj["v"] != BEACON_V:
        return None
    at = obj.get("at")
    if not isinstance(at, str):
        return None
    try:
        dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.timestamp()


def _beacon_in(path, now: float, bound: float):
    """(True, ts | None) when the beacon was read, (False, None) when it is missing, malformed or from the
    future beyond SKEW_S. A time after ``bound`` reads as (True, None)."""
    if not path or not isinstance(path, (str, Path)):
        return False, None
    p = Path(path)
    if not p.is_file():
        return False, None
    with open(p, "rb") as f:
        raw = f.read(BEACON_MAX_BYTES + 1)
    if len(raw) > BEACON_MAX_BYTES:
        return False, None
    try:
        t = beacon_time(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return False, None
    if t is None or t > float(now) + SKEW_S:
        return False, None
    return True, (t if t <= bound else None)


def newest_user_message(db_paths: Optional[Iterable], now: float, until: Optional[float] = None,
                        beacons: Optional[Iterable] = None) -> dict:
    """``{at, age_h, sources_read, sources_failed}``; ``at`` (ISO, UTC) and ``age_h`` are None when no store
    or beacon read has a message from the person. ``until`` (epoch seconds) ignores messages after it, e.g.
    this turn's own (catchup.py); by default the bound is ``now`` plus SKEW_S. Each beacon counts as one
    source. Never raises, never returns content."""
    newest, read, failed = None, 0, 0
    try:
        bound = float(now) + SKEW_S if until is None else float(until)
    except (TypeError, ValueError):
        bound = None
    sources = [(_newest_in, p) for p in db_paths or ()] + [(_beacon_in, p) for p in beacons or ()]
    for kind, path in sources:
        try:
            if bound is None:
                ok, t = False, None
            elif kind is _beacon_in:
                ok, t = _beacon_in(path, now, bound)
            else:
                ok, t = _newest_in(path, bound)
        except (OSError, ValueError, TypeError, OverflowError):
            ok, t = False, None
        if not ok:
            failed += 1
            continue
        read += 1
        if t is not None and (newest is None or t > newest):
            newest = t
    if newest is None:
        return {"at": None, "age_h": None, "sources_read": read, "sources_failed": failed}
    at = datetime.fromtimestamp(newest, timezone.utc).isoformat(timespec="seconds")
    return {"at": at, "age_h": max(0.0, float(now) - newest) / 3600, "sources_read": read,
            "sources_failed": failed}
