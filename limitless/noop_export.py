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

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from .presleep_hr import MAX_BPM, MEASURED, MIN_BPM
from .sleep import EVENING_FROM_H
from .state_reader import MAX_ASLEEP_S

SOURCE = "noop"              # the one source name the sleep rows carry: never a device, model or id
WEARABLE_KINDS = ("liveBLE", "historyBLE", "oura", "huami")   # pairedDevice.sourceKind read straight off a strap
ASLEEP_STAGES = ("light", "deep", "rem")
WINDOW_S = 30 * 60           # pre-sleep window: the half hour right before the night's onset, [onset - WINDOW_S, onset)
MIN_SAMPLES = 10             # fewer plausible heart-rate samples in that window: no row for the night
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


def _int(v) -> Optional[int]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return int(v)


def _stage_seconds(seg) -> tuple:
    """(stage name, seconds) for one stage entry of either NOOP list shape; (None, 0) when unreadable."""
    if not isinstance(seg, dict) or not isinstance(seg.get("stage"), str):
        return None, 0
    a, b, m = _int(seg.get("start")), _int(seg.get("end")), seg.get("min")
    if a is not None and b is not None:
        return seg["stage"], max(0, b - a)
    if not isinstance(m, bool) and isinstance(m, (int, float)) and math.isfinite(m) and m > 0:
        return seg["stage"], m * 60
    return seg["stage"], 0


def stages_asleep(text) -> Optional[int]:
    """Seconds asleep (light + deep + rem) from a NOOP ``stagesJSON``: a list of ``{start, end, stage}`` second
    spans, a list of ``{stage, min}`` minute totals, or one ``{awake, light, deep, rem}`` object of minutes.
    None when it is absent, unreadable or names no stage at all (so the efficiency, or nothing, is used)."""
    if not isinstance(text, str):
        return None
    try:
        got = json.loads(text)
    except ValueError:
        return None
    if isinstance(got, dict):
        got = [{"stage": k, "min": v} for k, v in got.items()]
    if not isinstance(got, list):
        return None
    total, any_stage = 0.0, False
    for seg in got:
        name, secs = _stage_seconds(seg)
        if name is None or secs <= 0:
            continue
        any_stage = True
        total += secs if name in ASLEEP_STAGES else 0
    return int(round(total)) if any_stage else None


def night_of(onset: float, tz=None) -> Optional[str]:
    """The night a sleep that began at ``onset`` belongs to: the evening it began (sleep.py's rule, so a sleep
    that began after midnight belongs to the date before)."""
    try:
        dt = datetime.fromtimestamp(onset, tz)
    except (OverflowError, OSError, ValueError):
        return None
    d = dt.date() if dt.hour >= EVENING_FROM_H else dt.date() - timedelta(days=1)
    return d.isoformat()


def _iso(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sessions(con, parts) -> list:
    onset = "COALESCE(s.startTsAdjusted, s.startTs)" if parts.get("adjusted") else "s.startTs"
    sql = (f"SELECT s.deviceId, {onset}, s.endTs, s.efficiency, s.stagesJSON, p.sourceKind "
           "FROM sleepSession s LEFT JOIN pairedDevice p ON p.id = s.deviceId")
    if parts.get("dismissed"):
        sql += (" WHERE NOT EXISTS (SELECT 1 FROM dismissedSleep d WHERE d.deviceId = s.deviceId "
                "AND d.startTs = s.startTs)")
    return con.execute(sql).fetchall()


def sleep_nights(sessions, tz=None) -> tuple:
    """(night -> the night's session dict, skipped counts) over ``(deviceId, onset, end, efficiency, stagesJSON,
    sourceKind)`` rows. Only a wearable source (WEARABLE_KINDS) counts; per night the session with the most
    sleep wins (an evening nap never stands for the night), the earlier onset on a tie."""
    best, skipped = {}, {"not_wearable": 0, "no_asleep_time": 0, "not_a_night": 0}
    for device, onset, end, eff, stages_json, kind in sessions:
        if kind not in WEARABLE_KINDS:
            skipped["not_wearable"] += 1
            continue
        onset, end = _int(onset), _int(end)
        if onset is None or end is None or not 0 < end - onset <= MAX_ASLEEP_S:
            skipped["not_a_night"] += 1
            continue
        asleep = stages_asleep(stages_json)
        if asleep is None:
            e = eff if not isinstance(eff, bool) and isinstance(eff, (int, float)) else None
            asleep = int(round((end - onset) * e)) if e is not None and math.isfinite(e) and 0 < e <= 1 else None
        if asleep is None:
            skipped["no_asleep_time"] += 1
            continue
        night = night_of(onset, tz)
        if night is None or not 0 < asleep <= MAX_ASLEEP_S:
            skipped["not_a_night"] += 1
            continue
        s = {"night": night, "device": device, "onset": onset, "end": end, "asleep_s": asleep}
        old = best.get(night)
        if old is None or (asleep, -onset) > (old["asleep_s"], -old["onset"]):
            best[night] = s
    return {n: best[n] for n in sorted(best)}, skipped


def presleep_bpm(con, device, onset: int) -> tuple:
    """(mean bpm rounded to a tenth | None, plausible samples) of ``device``'s own ``hrSample`` rows in
    ``[onset - WINDOW_S, onset)``: the window is anchored on the onset event, never a clock time. A sample outside
    presleep_hr's MIN_BPM..MAX_BPM is not a heart rate and is not counted; under MIN_SAMPLES is None."""
    rows = con.execute("SELECT bpm FROM hrSample WHERE deviceId = ? AND ts >= ? AND ts < ?",
                       (device, onset - WINDOW_S, onset)).fetchall()
    vals = [float(b) for (b,) in rows
            if not isinstance(b, bool) and isinstance(b, (int, float)) and math.isfinite(b) and MIN_BPM <= b <= MAX_BPM]
    if len(vals) < MIN_SAMPLES:
        return None, len(vals)
    return round(sum(vals) / len(vals), 1), len(vals)


def presleep_row(night: str, bpm: float) -> dict:
    """The presleep_hr_file row for one night: only the fields StateReader.presleep_hr_rows reads."""
    return {"night": night, "bpm": bpm, "modality": MEASURED}


def sleep_row(s: dict) -> dict:
    """The sleep_file row for one night: only the fields StateReader.sleep_rows reads."""
    return {"night": s["night"], "asleep_s": s["asleep_s"], "source": SOURCE, "start": _iso(s["onset"]),
            "end": _iso(s["end"])}


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
            nights, skipped = sleep_nights(_sessions(con, parts), tz)
            skipped["too_few_hr"] = 0
            pre = []
            for s in nights.values():
                bpm, _n = presleep_bpm(con, s["device"], s["onset"])
                if bpm is None:
                    skipped["too_few_hr"] += 1
                else:
                    pre.append(presleep_row(s["night"], bpm))
            out = _empty(None)
            out.update(sleep=[sleep_row(s) for s in nights.values()], presleep=pre, skipped=skipped)
            return out
        finally:
            con.close()
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return _empty(NOT_NOOP)
