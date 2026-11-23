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

Demo rows (mock_guard: a demo strap id, the demo dataset's ``device.name`` mark, or config
``mock_device_patterns``) are dropped before anything is counted, so a demo heart rate or night is never read;
the count is ``skipped["demo"]``. A database whose sessions are all demo rows is mock_guard.ONLY_DEMO.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import quote

from . import mock_guard
from .presleep_hr import MAX_BPM, MEASURED, MIN_BPM
from .sleep import EVENING_FROM_H
from .state_reader import MAX_ASLEEP_S, PRESLEEP_HR_CONFIG, SLEEP_CONFIG, StateReader, config, state_dir

SOURCE = "noop"              # the one source name the sleep rows carry: never a device, model or id
WEARABLE_KINDS = ("liveBLE", "historyBLE", "oura", "huami")   # pairedDevice.sourceKind read straight off a strap
# With no pairedDevice row (a re-pair can orphan a strap's history, NOOP #1193) the id's own namespace decides:
# NOOP mints strap ids as "whoop-..."/"oura-..." (WhoopSerialIdentity.ID_PREFIX); "my-whoop" is the legacy seed.
STRAP_ID_PREFIXES = ("whoop-", "oura-")
STRAP_IDS = ("my-whoop",)


def is_wearable(device, kind) -> bool:
    """A strap session: its paired row's sourceKind when there is one, else the strap id namespace."""
    if kind is not None:
        return kind in WEARABLE_KINDS
    return isinstance(device, str) and (device in STRAP_IDS or device.startswith(STRAP_ID_PREFIXES))
ASLEEP_STAGES = ("light", "deep", "rem")
WINDOW_S = 30 * 60           # pre-sleep window: the half hour right before the night's onset, [onset - WINDOW_S, onset)
MIN_SAMPLES = 10             # fewer plausible heart-rate samples in that window: no row for the night
DB_CONFIG = "noop_db"
USAGE = "usage: limitless-noop-export [--write]"
NO_DB = f"nothing to export: no NOOP database configured (set \"{DB_CONFIG}\" in config.json)"
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


def _device_names(con) -> dict:
    """NOOP's ``device`` table as id -> name ({} when the table or a column is missing): the demo seeders mark
    their dataset only by this name (mock_guard.NAME_MARK)."""
    if not {"id", "name"} <= (_columns(con, "device") or set()):
        return {}
    return {i: n for i, n in con.execute("SELECT id, name FROM device").fetchall()}


def drop_demo(sessions, names: dict, cfg=None) -> tuple:
    """(the sessions whose device is not a demo device, how many were dropped): mock_guard over each session's
    deviceId and that id's ``device.name``."""
    real, n = [], 0
    for s in sessions:
        if mock_guard.is_mock({"deviceId": s[0], "name": names.get(s[0])}, cfg):
            n += 1
        else:
            real.append(s)
    return real, n


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
        if not is_wearable(device, kind):
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


def read(db_path, tz=None, cfg=None) -> dict:
    """The nightly rows from the NOOP DB at ``db_path``, demo rows left out (drop_demo, with config ``cfg``'s
    mock_device_patterns); never raises, never writes."""
    try:
        path = Path(db_path)
        if not path.is_file():
            return _empty(NO_FILE)
        con = sqlite3.connect(uri(path), uri=True)
        try:
            reason, parts = schema(con)
            if reason is not None:
                return _empty(reason)
            sessions, demo = drop_demo(_sessions(con, parts), _device_names(con), cfg)
            if demo and not sessions:
                out = _empty(mock_guard.ONLY_DEMO)
                out["skipped"] = {"demo": demo}
                return out
            nights, skipped = sleep_nights(sessions, tz)
            skipped["too_few_hr"] = 0
            if demo:
                skipped["demo"] = demo
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


_ONES = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def words(n: int) -> str:
    """A count spelled out (0 is "no"), so no digit reaches the output; "many" past 9999."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return _ONES[n // 100] + " hundred" + (" " + words(n % 100) if n % 100 else "")
    if n < 10000:
        return _ONES[n // 1000] + " thousand" + (" " + words(n % 1000) if n % 1000 else "")
    return "many"


def nights_words(n: int) -> str:
    return f"{words(n)} night" + ("" if n == 1 else "s")


def db_path(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[Path]:
    """Config ``noop_db``: the operator's copy of the NOOP DB; a relative path is in the state dir. None unset."""
    v = config(env, home).get(DB_CONFIG)
    if not isinstance(v, str) or not v.strip():
        return None
    p = Path(v.strip()).expanduser()
    return p if p.is_absolute() else state_dir(env, home) / p


def _line(row: dict) -> str:
    return json.dumps(row) + "\n"


def merge(existing: str, rows: list, key: tuple) -> tuple:
    """(new text, rows new or changed): ``rows`` merged into the JSONL text ``existing`` by ``key`` (night plus
    source or modality). A row of ours replaces the one with the same key; every other row is kept, as are lines
    that are not object rows with a night (first, in their order). Object rows are sorted by key: the output
    depends only on the content, so a rerun gives the same bytes."""
    keep, byk = [], {}
    for ln in existing.splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            r = None
        if not isinstance(r, dict) or not isinstance(r.get("night"), str):
            if ln.strip():
                keep.append(ln + "\n")
            continue
        byk.setdefault(tuple(str(r.get(k)) for k in key), r)
    changed = 0
    for r in rows:
        k = tuple(str(r.get(f)) for f in key)
        if byk.get(k) != r:
            changed += 1
        byk[k] = r
    return "".join(keep) + "".join(_line(byk[k]) for k in sorted(byk)), changed


def write_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` through a temp file in the same directory and a rename, mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


TARGETS = (("sleep file", SLEEP_CONFIG, "sleep", ("night", "source")),
           ("pre-sleep heart-rate file", PRESLEEP_HR_CONFIG, "presleep", ("night", "modality")))
SKIP_WORDS = (("not_wearable", "session", "not from a wearable"), ("no_asleep_time", "session", "with no asleep time"),
              ("not_a_night", "session", "not a night"), ("too_few_hr", "night", "with too few heart-rate samples"))


def demo_words(n: int) -> str:
    """'' for none, else mock_guard.LEFT_OUT with the count in words."""
    if not n:
        return ""
    return f"; {mock_guard.LEFT_OUT} ({words(n)} session{'' if n == 1 else 's'} from a demo or sample device)"


def _skipped(skipped: dict) -> str:
    parts = [f"{words(skipped[k])} {noun}{'' if skipped[k] == 1 else 's'} {why}"
             for k, noun, why in SKIP_WORDS if skipped.get(k)]
    return (("; skipped " + ", ".join(parts)) if parts else "") + demo_words(skipped.get("demo", 0))


def _target(reader: StateReader, cfg_key: str, env, home) -> Optional[Path]:
    return reader.sleep_file(env, home) if cfg_key == SLEEP_CONFIG else reader.presleep_hr_file(env, home)


def main(argv, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None, tz=None, out=None,
         err=None) -> int:
    """The CLI: 0 when done or when there is nothing to export (one line why), 1 when a file cannot be written,
    2 for bad arguments. Prints counts in words and never a path, a device or a reading."""
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    env = os.environ if env is None else env
    args = list(argv)
    if args not in ([], ["--write"]):
        print(USAGE, file=err)
        return 2
    write = args == ["--write"]
    db = db_path(env, home)
    if db is None:
        print(NO_DB, file=out)
        return 0
    got = read(db, tz, config(env, home))
    if got["reason"] is not None:
        print(got["reason"], file=out)
        return 0
    found = (f"{nights_words(len(got['sleep']))} of wearable sleep and {nights_words(len(got['presleep']))} of "
             f"pre-sleep heart rate in the NOOP database{_skipped(got['skipped'])}")
    if not write:
        print(f"dry run: {found}; nothing written (run with --write to write them)", file=out)
        return 0
    print(f"found {found}", file=out)
    reader, code = StateReader(state_dir(env, home)), 0
    for name, cfg_key, field, key in TARGETS:
        path = _target(reader, cfg_key, env, home)
        if path is None:
            print(f"{name}: not configured (set \"{cfg_key}\" in config.json), not written", file=out)
            continue
        try:
            old = path.read_text(encoding="utf-8") if path.is_file() else ""
            text, changed = merge(old, got[field], key)
            if text == old:
                print(f"{name}: unchanged", file=out)
                continue
            write_atomic(path, text)
        except (OSError, ValueError) as e:
            print(f"{name}: not written: {getattr(e, 'strerror', None) or type(e).__name__}", file=err)
            code = 1
            continue
        print(f"{name}: written, {nights_words(changed)} new or changed", file=out)
    return code
