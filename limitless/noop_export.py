"""Wearable sleep and pre-sleep heart rate from a copy of the NOOP app's database, for sleep_file and presleep_hr_file.

    got = read(db_path, tz=None)
    # {"sleep": [{"night", "asleep_s", "source", "start", "end"}, ...],
    #  "presleep": [{"night", "bpm", "modality": "measured"}, ...], "reason": str | None, "skipped": {...}}

NOOP (github.com/ryanbr/noop) is an open-source, on-device companion app for wearable straps and rings. Its
Android Room schema (android/app/src/main/java/com/noop/data/Entities.kt and PairedDevice.kt) has the tables read
here: ``sleepSession`` (deviceId, startTs, endTs, efficiency, stagesJSON, optional startTsAdjusted),
``hrSample`` (deviceId, ts, bpm) and ``pairedDevice`` (id, sourceKind). Times are unix seconds.

Read-only, always: the file is a copy, opened through a ``file:...?mode=ro&immutable=1`` URI, so nothing is
written, created or locked beside it. A missing table or column is one plain reason (SCHEMA_PREFIX + what is
missing) and no rows: never a guess from a schema this module does not know.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional
from urllib.parse import quote

NO_FILE = "no NOOP database at the configured path"
NOT_NOOP = "the configured file is not a readable SQLite database"
SCHEMA_PREFIX = "not a NOOP database this exporter knows: "
REQUIRED = {
    "sleepSession": ("deviceId", "startTs", "endTs", "efficiency", "stagesJSON"),
    "hrSample": ("deviceId", "ts", "bpm"),
    "pairedDevice": ("id", "sourceKind"),
}


def uri(path) -> str:
    """The read-only, immutable SQLite URI for ``path``: nothing is ever written or created beside it."""
    return "file:" + quote(str(Path(path).resolve())) + "?mode=ro&immutable=1"


def _columns(con, table) -> Optional[set]:
    rows = con.execute(f"PRAGMA table_info(\"{table}\")").fetchall()
    return {r[1] for r in rows} if rows else None


def schema(con) -> tuple:
    """(reason | None, optional parts present): the first missing table or column, in REQUIRED order."""
    for table, cols in REQUIRED.items():
        have = _columns(con, table)
        if have is None:
            return SCHEMA_PREFIX + f"no table {table}", {}
        for c in cols:
            if c not in have:
                return SCHEMA_PREFIX + f"no column {table}.{c}", {}
    adjusted = "startTsAdjusted" in (_columns(con, "sleepSession") or set())
    dismissed = {"deviceId", "startTs"} <= (_columns(con, "dismissedSleep") or set())
    return None, {"adjusted": adjusted, "dismissed": dismissed}


def _empty(reason) -> dict:
    return {"sleep": [], "presleep": [], "reason": reason, "skipped": {}}


def read(db_path, tz=None) -> dict:
    """The nightly rows from the NOOP DB at ``db_path``; never raises, never writes."""
    try:
        path = Path(db_path)
        if not path.is_file():
            return _empty(NO_FILE)
        con = sqlite3.connect(uri(path), uri=True)
        try:
            reason, parts = schema(con)
            if reason is not None:
                return _empty(reason)
            return _empty(None)
        finally:
            con.close()
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return _empty(NOT_NOOP)
