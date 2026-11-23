"""A synthetic NOOP app database for the noop_export tests and example. Made-up rows only.

The schema is a small subset of the public NOOP Android Room entities (github.com/ryanbr/noop,
android/app/src/main/java/com/noop/data/Entities.kt and PairedDevice.kt): table and column names only, the
columns the exporter reads plus the identifying ones a privacy test plants values in. Timestamps are unix
seconds, as in NOOP.
"""
import json
import sqlite3
from pathlib import Path

TABLES = {
    "pairedDevice": ("id TEXT PRIMARY KEY NOT NULL, brand TEXT NOT NULL, model TEXT NOT NULL, nickname TEXT, "
                     "peripheralId TEXT, sourceKind TEXT NOT NULL, capabilities TEXT NOT NULL, status TEXT NOT NULL, "
                     "addedAt INTEGER NOT NULL, lastSeenAt INTEGER NOT NULL"),
    "device": "id TEXT PRIMARY KEY NOT NULL, mac TEXT, name TEXT, firstSeen INTEGER, lastSeen INTEGER",
    "sleepSession": ("deviceId TEXT NOT NULL, startTs INTEGER NOT NULL, endTs INTEGER NOT NULL, efficiency REAL, "
                     "restingHr INTEGER, avgHrv REAL, stagesJSON TEXT, userEdited INTEGER NOT NULL DEFAULT 0, "
                     "startTsAdjusted INTEGER, PRIMARY KEY(deviceId, startTs)"),
    "hrSample": "deviceId TEXT NOT NULL, ts INTEGER NOT NULL, bpm INTEGER NOT NULL, synced INTEGER NOT NULL DEFAULT 0, "
                "PRIMARY KEY(deviceId, ts)",
    "dismissedSleep": "deviceId TEXT NOT NULL, startTs INTEGER NOT NULL, endTs INTEGER NOT NULL, "
                      "managementVisible INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(deviceId, startTs)",
}
RING = "ring-0001"          # a strap-direct wearable (sourceKind "oura")
PHONE = "apple-health"      # the phone's health-store bucket: not a wearable
IMPORT = "import-0001"      # a file import: not read as the wearable


def stages(onset, asleep_s, awake_s=0):
    """A NOOP-style computed stage list ``[{start, end, stage}]`` tiling ``awake_s`` awake then sleep."""
    out, t = [], onset
    if awake_s:
        out.append({"end": t + awake_s, "stage": "wake", "start": t})
        t += awake_s
    third = asleep_s // 3
    for name, d in (("light", third), ("deep", third), ("rem", asleep_s - 2 * third)):
        out.append({"end": t + d, "stage": name, "start": t})
        t += d
    return json.dumps(out)


def make_db(path, *, sessions=(), hr=(), devices=None, dismissed=(), drop=None, drop_column=None):
    """Write a synthetic NOOP DB at ``path``.

    sessions: (deviceId, startTs, endTs, efficiency, stagesJSON[, startTsAdjusted]) tuples.
    hr: (deviceId, ts, bpm) tuples. devices: pairedDevice rows as dicts (default: one ring, one import).
    drop: a table name to leave out; drop_column: (table, column) to leave out of the schema.
    """
    path = Path(path)
    devices = devices if devices is not None else [
        {"id": RING, "brand": "Ring", "model": "Ring", "nickname": None, "peripheralId": None,
         "sourceKind": "oura", "capabilities": "hr,sleep", "status": "active", "addedAt": 0, "lastSeenAt": 0},
        {"id": IMPORT, "brand": "Import", "model": "CSV", "nickname": None, "peripheralId": None,
         "sourceKind": "fileImport", "capabilities": "sleep", "status": "paired", "addedAt": 0, "lastSeenAt": 0},
    ]
    con = sqlite3.connect(str(path))
    try:
        con.execute("PRAGMA synchronous=OFF")   # a throwaway test file: no fsync
        for name, cols in TABLES.items():
            if name == drop:
                continue
            if drop_column and drop_column[0] == name:
                cols = ", ".join(c for c in cols.split(", ") if not c.startswith(drop_column[1] + " "))
            con.execute(f"CREATE TABLE {name} ({cols})")
        if drop != "pairedDevice":
            for d in devices:
                keys = [k for k in d if not (drop_column and drop_column == ("pairedDevice", k))]
                con.execute(f"INSERT INTO pairedDevice ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                            [d[k] for k in keys])
        if drop != "sleepSession":
            for s in sessions:
                s = tuple(s) + (None,) * (6 - len(s))
                cols = ["deviceId", "startTs", "endTs", "efficiency", "stagesJSON", "startTsAdjusted"]
                vals = list(s)
                if drop_column and drop_column[0] == "sleepSession":
                    i = cols.index(drop_column[1])
                    del cols[i], vals[i]
                con.execute(f"INSERT INTO sleepSession ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                            vals)
        if drop != "hrSample":
            con.executemany("INSERT INTO hrSample (deviceId, ts, bpm) VALUES (?, ?, ?)", list(hr))
        if drop != "dismissedSleep":
            con.executemany("INSERT INTO dismissedSleep (deviceId, startTs, endTs) VALUES (?, ?, ?)",
                            list(dismissed))
        con.commit()
    finally:
        con.close()
    return path


def hr_before(device, onset, bpm, n=30, step=60):
    """``n`` samples at ``bpm``, one every ``step`` seconds, ending one step before ``onset``."""
    return [(device, onset - step * (i + 1), bpm) for i in range(n)]
