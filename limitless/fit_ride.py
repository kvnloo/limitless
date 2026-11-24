"""One bike ride exported as a Garmin FIT file (a CAROL bike's "Download .FIT") into one rides-file row.

    fit_ride.read(data)        # bytes -> {"start", "duration_s", "kind": "ride", "source": "carol-fit"} | reason
    fit_ride.read_path(path)   # the same for a file on disk; an unreadable file is the UNREADABLE reason
    fit_ride.run(paths, rides_file, write=False)   # bin/limitless-import-fit: dry run unless write

A minimal FIT reader for exactly what a ride row needs, nothing more:

- the file header (12 or 14 bytes, the ".FIT" signature, the data size); the header CRC is checked when the
  header carries a non-zero one, and the file CRC always;
- definition and data messages (local message types, little or big endian, compressed-timestamp headers),
  with developer fields skipped by their size;
- the first ``session`` message (global 18): ``start_time`` (field 2, seconds since the FIT epoch
  1989-12-31T00:00:00Z), ``total_elapsed_time`` (field 7, milliseconds) or else ``total_timer_time``
  (field 8), and ``sport`` (field 5; cycling is 2);
- the ``activity`` message (global 34): ``local_timestamp`` (field 5) minus its ``timestamp`` gives the
  rider's UTC offset, rounded to a quarter hour; without one the start is written in UTC with "Z".

Every other message (per-second power, heart rate, cadence samples, laps, device info) is stepped over unread:
those numbers are T0 and never leave the file. Bad bytes never raise: the result is a reason in words.

Writing appends to the ONE configured rides file (StateReader.rides_file, read by StateReader.ride_rows),
never a second store: only rows whose start instant and source are not already there (ride_rows would drop
them anyway), through ranked_ledger.append (one flocked append, mode 0600). Never rewrites or deletes.
Stdlib only, Python 3.9+. Nothing here reads the network, reads the clock or sends.
"""
from __future__ import annotations

import json
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional, Union

KIND = "ride"
SOURCE = "carol-fit"
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
CYCLING = 2
SESSION, ACTIVITY = 18, 34
TIMESTAMP = 253
MIN_ABSOLUTE = 0x10000000     # FIT: a date_time below this is seconds since power-on, not a date
QUARTER_HOUR = 900
MAX_OFFSET_S = 14 * 3600

NOT_FIT = "not a FIT file"
BAD_HEADER_CRC = "the FIT header check does not match, the file is damaged"
BAD_CRC = "the FIT file check does not match, the file is damaged"
TRUNCATED = "the FIT file is cut short"
DAMAGED = "the FIT records do not read, the file is damaged"
NO_SESSION = "no ride summary in the file"
NO_START = "the ride summary has no start time"
NOT_CYCLING = "not a bike ride"
ZERO_DURATION = "the ride has no duration"
UNREADABLE = "the file could not be read"
REASONS = (NOT_FIT, BAD_HEADER_CRC, BAD_CRC, TRUNCATED, DAMAGED, NO_SESSION, NO_START, NOT_CYCLING,
           ZERO_DURATION, UNREADABLE)

_TABLE = (0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
          0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400)
_ZERO_INVALID = {0x0A, 0x0B, 0x0C}   # uint8z, uint16z, uint32z: zero is the invalid value


def crc16(data: bytes) -> int:
    """The FIT CRC-16 (the SDK's nibble table) of ``data``."""
    crc = 0
    for b in data:
        for nib in (b & 0xF, b >> 4):
            tmp = _TABLE[crc & 0xF]
            crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _TABLE[nib]
    return crc


class _Bad(Exception):
    """A record that does not read; carries the reason."""


def _uint(raw: bytes, big: bool, base: int) -> Optional[int]:
    """An unsigned field value, or None when it is the FIT invalid value or not a one, two or four byte int."""
    if len(raw) not in (1, 2, 4):
        return None
    v = int.from_bytes(raw, "big" if big else "little")
    if (base & 0x1F) in _ZERO_INVALID:
        return None if v == 0 else v
    return None if v == (1 << (8 * len(raw))) - 1 else v


def _messages(data: bytes, start: int, end: int):
    """Yield ``(global_num, {field_num: value})`` for the session and activity messages in data[start:end]."""
    defs = {}
    last_ts = None
    pos = start
    while pos < end:
        hdr = data[pos]
        pos += 1
        if hdr & 0x80:                                   # compressed-timestamp data message
            local, offset = (hdr >> 5) & 0x3, hdr & 0x1F
            ts = None
            if last_ts is not None:
                ts = (last_ts & ~0x1F) + offset
                if offset < (last_ts & 0x1F):
                    ts += 0x20
                last_ts = ts
        elif hdr & 0x40:                                 # definition message
            local = hdr & 0x0F
            if pos + 5 > end:
                raise _Bad(DAMAGED)
            big = data[pos + 1] == 1
            gnum = struct.unpack_from(">H" if big else "<H", data, pos + 2)[0]
            n = data[pos + 4]
            pos += 5
            if pos + 3 * n > end:
                raise _Bad(DAMAGED)
            fields = [(data[pos + 3 * i], data[pos + 3 * i + 1], data[pos + 3 * i + 2]) for i in range(n)]
            pos += 3 * n
            dev_size = 0
            if hdr & 0x20:                               # developer fields: skipped by size
                if pos + 1 > end:
                    raise _Bad(DAMAGED)
                nd = data[pos]
                pos += 1
                if pos + 3 * nd > end:
                    raise _Bad(DAMAGED)
                dev_size = sum(data[pos + 3 * i + 1] for i in range(nd))
                pos += 3 * nd
            defs[local] = (big, gnum, fields, dev_size)
            continue
        else:                                            # normal data message
            local, ts = hdr & 0x0F, None
        if local not in defs:
            raise _Bad(DAMAGED)
        big, gnum, fields, dev_size = defs[local]
        values = {}
        for num, size, base in fields:
            if pos + size > end:
                raise _Bad(DAMAGED)
            if gnum in (SESSION, ACTIVITY) or num == TIMESTAMP:
                values[num] = _uint(data[pos:pos + size], big, base)
            pos += size
        if pos + dev_size > end:
            raise _Bad(DAMAGED)
        pos += dev_size
        if values.get(TIMESTAMP) is not None:
            last_ts = values[TIMESTAMP]
        elif ts is not None:
            values[TIMESTAMP] = ts
        if gnum in (SESSION, ACTIVITY):
            yield gnum, values


def _row(session: dict, offset_s: Optional[int]) -> Union[dict, str]:
    start = session.get(2)
    if start is None or start < MIN_ABSOLUTE:
        return NO_START
    if session.get(5) != CYCLING:
        return NOT_CYCLING
    ms = next((v for v in (session.get(7), session.get(8)) if v is not None and v > 0), None)
    secs = int(round(ms / 1000.0)) if ms is not None else 0
    if secs <= 0:
        return ZERO_DURATION
    at = FIT_EPOCH + timedelta(seconds=start)
    if offset_s is None:
        when = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        when = at.astimezone(timezone(timedelta(seconds=offset_s))).isoformat()
    return {"start": when, "duration_s": secs, "kind": KIND, "source": SOURCE}


def _offset(activity: Optional[dict]) -> Optional[int]:
    if not activity or activity.get(5) is None or activity.get(TIMESTAMP) is None:
        return None
    off = int(round((activity[5] - activity[TIMESTAMP]) / QUARTER_HOUR)) * QUARTER_HOUR
    return off if abs(off) <= MAX_OFFSET_S else None


def read(data) -> Union[dict, str]:
    """The ride row of one FIT file's bytes, or the reason (one of REASONS) there is none. Never raises."""
    try:
        if not isinstance(data, (bytes, bytearray)) or len(data) < 12:
            return NOT_FIT
        data = bytes(data)
        hs = data[0]
        if data[8:12] != b".FIT" or hs not in (12, 14):
            return NOT_FIT
        if len(data) < hs:
            return TRUNCATED
        size = struct.unpack_from("<I", data, 4)[0]
        if hs == 14:
            hcrc = struct.unpack_from("<H", data, 12)[0]
            if hcrc and hcrc != crc16(data[:12]):
                return BAD_HEADER_CRC
        end = hs + size
        if len(data) < end + 2:
            return TRUNCATED
        if crc16(data[:end]) != struct.unpack_from("<H", data, end)[0]:
            return BAD_CRC
        session = activity = None
        for gnum, values in _messages(data, hs, end):
            if gnum == SESSION and session is None:
                session = values
            elif gnum == ACTIVITY and activity is None:
                activity = values
        if session is None:
            return NO_SESSION
        return _row(session, _offset(activity))
    except _Bad as e:
        return str(e)
    except Exception:  # noqa: BLE001 - bad bytes are a reason, never a traceback
        return DAMAGED


def read_path(path) -> Union[dict, str]:
    """read() of the file at ``path``; UNREADABLE when it cannot be opened. Never raises."""
    try:
        data = Path(path).read_bytes()
    except (OSError, TypeError, ValueError):
        return UNREADABLE
    return read(data)


# --- the importer (bin/limitless-import-fit) ----------------------------------------------------------------

NO_RIDES_FILE = "no rides file set (config rides_file)"
NO_FOLDER = "the rides file's folder does not exist"
NEW, DUPLICATE, SKIPPED = "new", "duplicate", "skipped"
ALREADY = "already in the rides file"
TWICE = "the same ride as an earlier file"
_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
          "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty")


def count_words(n: int, noun: str) -> str:
    """``n`` of ``noun`` in words, digit-free: "no files", "one file", ..., "more than twenty files"."""
    if n > len(_WORDS) - 1:
        return f"more than {_WORDS[-1]} {noun}s"
    return f"{_WORDS[max(n, 0)]} {noun}{'' if n == 1 else 's'}"


def rides_words(n: int) -> str:
    """``n`` rides in words, digit-free: "no rides", "one ride", ..., "more than twenty rides"."""
    return count_words(n, "ride")


def _instant(start) -> Optional[float]:
    try:
        dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.timestamp() if dt.tzinfo is not None and dt.utcoffset() is not None else None


def known_instants(rides_file) -> set:
    """The start instants of the rows already in the rides file with this importer's source (what ride_rows
    would dedupe a new row against). A missing or unreadable file is an empty set."""
    try:
        text = Path(rides_file).read_text(errors="replace")
    except (OSError, TypeError, ValueError):
        return set()
    out = set()
    for ln in text.splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("source") == SOURCE:
            at = _instant(r.get("start"))
            if at is not None:
                out.add(at)
    return out


def run(paths: Iterable, rides_file, write: bool = False) -> dict:
    """``{"rides_file", "written", "added", "why", "files": [{"path", "status", "reason", "row"}]}`` for importing
    the FIT files at ``paths``. Dry run unless ``write``; a write appends only the new rows (append only)."""
    seen = known_instants(rides_file) if rides_file is not None else set()
    files, new, this_run = [], [], set()
    for p in paths:
        got = read_path(p)
        item = {"path": str(p), "status": SKIPPED, "reason": None, "row": None}
        if isinstance(got, str):
            item["reason"] = got
        else:
            item["row"] = got
            at = _instant(got["start"])
            if at in seen:
                item["status"] = DUPLICATE
                item["reason"] = TWICE if at in this_run else ALREADY
            else:
                seen.add(at)
                this_run.add(at)
                new.append(got)
                item["status"] = NEW
        files.append(item)
    out = {"rides_file": None if rides_file is None else str(rides_file), "written": False, "added": len(new),
           "why": "", "files": files}
    if not write:
        return out
    if rides_file is None:
        out.update(added=0, why=NO_RIDES_FILE)
        return out
    if new:
        if not Path(rides_file).parent.is_dir():
            out.update(added=0, why=NO_FOLDER)
            return out
        from . import ranked_ledger   # the package's flocked 0600 JSONL append
        ranked_ledger.append(rides_file, [dict(r) for r in new])
    out["written"] = True
    return out


def words(out: dict, write: bool) -> list:
    """The CLI's plain lines: one per file, then the total, digit-free (file names as given)."""
    lines = []
    for f in out["files"]:
        name = Path(f["path"]).name
        if f["status"] == NEW:
            what = "not added" if out["why"] else ("added" if out["written"] else "would add") + " one ride"
        else:
            what = f["reason"]
        lines.append(f"{name}: {what}")
    if out["why"]:
        lines.append(f"added no rides: {out['why']}")
    else:
        lines.append(("added " if out["written"] else "would add ") + rides_words(out["added"]))
    return lines
