"""The person's own phone actions from an ActivityWatch-for-Android SQLite copy, as screen-event rows.

    rows = person_rows(db_path)        # [{"ts": epoch_s, "type": "KEYGUARD_HIDDEN" | "USER_INTERACTION"}]
    starts = app_starts(db_path)       # [{"ts": epoch_s, "app": str, "package": str}] (feeds_evidence)

An unlock (bucket type ``os.lockscreen.unlocks``) becomes ``KEYGUARD_HIDDEN``; the start of an
app-in-foreground span (bucket type ``currentwindow``) becomes ``USER_INTERACTION``. The rows feed
wake_proxy.events_from_screen like screen-events.jsonl rows do. Buckets are found by ``type``, never by
name. AW stores ``starttime`` in epoch nanoseconds; rows here are epoch seconds.

The DB is opened read-only (``mode=ro``): nothing here writes, creates or locks it. A missing file, a
locked or malformed DB, missing tables or a row with bad JSON never raises; it reads as fewer rows or
``[]``. ``app_starts`` reads the same app-span starts with the app's ``app`` and ``package`` names
(empty strings when the row has none). Rows are bounded: ``since_s`` if given, else the WINDOW_S before the newest row. Stdlib only,
Python 3.9+.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional
from urllib.parse import quote

UNLOCKS = "os.lockscreen.unlocks"
CURRENT_WINDOW = "currentwindow"
TYPE_OF = {UNLOCKS: "KEYGUARD_HIDDEN", CURRENT_WINDOW: "USER_INTERACTION"}
WINDOW_S = 3 * 24 * 3600     # default bound: this long before the newest row
NS = 1_000_000_000
BUSY_TIMEOUT_S = 0.5         # a DB the phone sync holds locked reads as [] rather than waiting

_QUERY = (
    "SELECT b.type, e.starttime, e.data FROM events e JOIN buckets b ON b.id = e.bucketrow "
    "WHERE b.type IN (?, ?) AND typeof(e.starttime) = 'integer' AND e.starttime >= ? "
    "ORDER BY e.starttime, e.id"
)
_NEWEST = (
    "SELECT MAX(e.starttime) FROM events e JOIN buckets b ON b.id = e.bucketrow "
    "WHERE b.type IN (?, ?) AND typeof(e.starttime) = 'integer'"
)


def _json_ok(data) -> bool:
    if data is None:
        return True
    try:
        return isinstance(json.loads(data), dict)
    except (TypeError, ValueError):
        return False


def person_rows(db_path, since_s: Optional[float] = None) -> list:
    """``{"ts", "type"}`` rows, oldest first, for unlocks and app-span starts in the AW DB at ``db_path``."""
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
        if since_s is None:
            newest = con.execute(_NEWEST, (UNLOCKS, CURRENT_WINDOW)).fetchone()[0]
            if newest is None:
                return []
            since_ns = int(newest) - WINDOW_S * NS
        else:
            since_ns = int(float(since_s) * NS)
        rows = con.execute(_QUERY, (UNLOCKS, CURRENT_WINDOW, since_ns)).fetchall()
    except (sqlite3.Error, ValueError, OverflowError, TypeError):
        return []
    finally:
        con.close()
    return [{"ts": start / NS, "type": TYPE_OF[btype]} for btype, start, data in rows if _json_ok(data)]


_APP_QUERY = (
    "SELECT e.starttime, e.data FROM events e JOIN buckets b ON b.id = e.bucketrow "
    "WHERE b.type = ? AND typeof(e.starttime) = 'integer' AND e.starttime >= ? ORDER BY e.starttime, e.id"
)
_APP_NEWEST = ("SELECT MAX(e.starttime) FROM events e JOIN buckets b ON b.id = e.bucketrow "
               "WHERE b.type = ? AND typeof(e.starttime) = 'integer'")


def _names(data) -> Optional[dict]:
    try:
        d = json.loads(data) if data is not None else {}
    except (TypeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    return {k: d[k] if isinstance(d.get(k), str) else "" for k in ("app", "package")}


def app_starts(db_path, since_s: Optional[float] = None) -> list:
    """``{"ts", "app", "package"}`` rows, oldest first, for each app-in-foreground span start in the AW DB.

    Same read-only open and bounds as person_rows; a missing, locked or broken DB is ``[]``.
    """
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
        if since_s is None:
            newest = con.execute(_APP_NEWEST, (CURRENT_WINDOW,)).fetchone()[0]
            if newest is None:
                return []
            since_ns = int(newest) - WINDOW_S * NS
        else:
            since_ns = int(float(since_s) * NS)
        rows = con.execute(_APP_QUERY, (CURRENT_WINDOW, since_ns)).fetchall()
    except (sqlite3.Error, ValueError, OverflowError, TypeError):
        return []
    finally:
        con.close()
    out = []
    for start, data in rows:
        names = _names(data)
        if names is not None:
            out.append({"ts": start / NS, **names})
    return out
