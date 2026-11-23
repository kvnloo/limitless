"""Idea ledger: the one official record every idea lands in, appended by a job, never rewritten.

    rows = new_rows(captures, ledger_rows, cursor)   # the captures not yet in the ledger, as idea rows
    out = append(ledger_path, rows, write=False)    # dry run by default

Ideas arrive as quick captures (limitless_capture) and as plain messages saved by bedtime capture; both are
written by capture.py to captures.jsonl, so StateReader.captures() is the only input. Message stores are never
read for content (owner_messages reads timestamps only). An idea row is
``{"kind": "idea", "id", "at", "text", "source", "status": "new"}``: ``at`` and ``source`` as captured, ``id``
``idea_`` plus a short sha256 of the normalised text (NFKC, case-folded, whitespace collapsed). The same
normalised text is one idea: a re-run, or the same thought captured twice, appends nothing.

Where: the configured file IS the one record: $LIMITLESS_IDEA_LEDGER, else config ``idea_ledger`` (a relative
path is in the state dir; StateReader.idea_ledger_path). Not set: the job does nothing and says why ("no idea
ledger set"). There is no default path, and nothing here creates a folder or a second store. ``append`` is a
dry run unless ``write``; a write is one ``os.write`` of whole newline-terminated lines with ``O_APPEND`` (a
file it creates is mode 0600). The captures file itself is never the ledger.

``cursor`` (cursor(ledger_rows): the newest idea ``at`` already in the ledger) skips captures at or before it,
so an idea the person removed from the ledger in a review is not appended again.

The code never triages, ranks or starts anything: every row it writes is ``status: "new"``; the person changes
a status by hand in a review. Existing rows are never rewritten or reordered. ``new_rows`` and ``cursor`` are
pure. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Iterable, Mapping, Optional

from . import capture
from .state_reader import StateReader, parse_ts

KIND, NEW = "idea", "new"
UNKNOWN_SOURCE = "unknown"
ID_PREFIX, ID_HEX = "idea_", 16
_WS = re.compile(r"\s+")
NO_LEDGER = "no idea ledger set"
NO_DIR = "the idea ledger's folder does not exist"
SAME_AS_CAPTURES = "the idea ledger cannot be the captures file"
NOTHING_NEW = "no new ideas"


def normalise(text: str) -> str:
    """The text an idea is deduped on: NFKC, case-folded, whitespace collapsed and trimmed."""
    return _WS.sub(" ", unicodedata.normalize("NFKC", text).casefold()).strip()


def idea_id(text: str) -> str:
    """``idea_`` plus the first sixteen hex digits of sha256(normalise(text)): stable, and not the text."""
    return ID_PREFIX + hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()[:ID_HEX]


def _ideas(rows: Optional[Iterable]) -> list:
    return [r for r in rows or () if isinstance(r, dict) and r.get("kind") == KIND]


def cursor(ledger_rows: Optional[Iterable]) -> Optional[str]:
    """The ``at`` of the newest idea row in the ledger (as written), or None for an empty ledger."""
    best = None
    for r in _ideas(ledger_rows):
        t = parse_ts(r.get("at")) if isinstance(r.get("at"), str) else None
        if t is not None and (best is None or t > best[0]):
            best = (t, r["at"])
    return None if best is None else best[1]


def _row(c) -> Optional[tuple]:
    """(time, idea row) for one valid capture, else None."""
    if not isinstance(c, dict):
        return None
    text, at = c.get("text"), c.get("at")
    if not isinstance(text, str) or not text.strip() or not isinstance(at, str):
        return None
    t = parse_ts(at)
    if t is None:
        return None
    src = c.get("source")
    src = src if isinstance(src, str) and src.strip() else UNKNOWN_SOURCE
    return t, {"kind": KIND, "id": idea_id(text), "at": at, "text": text, "source": src, "status": NEW}


def new_rows(captures: Optional[Iterable], ledger_rows: Optional[Iterable], cursor_at=None) -> list:
    """The captures not yet in the ledger, as new idea rows, oldest first. A capture without text or a
    readable time is skipped; one at or before ``cursor_at`` (ISO or epoch) is skipped; one whose id is
    already in the ledger (or earlier in this batch) is skipped. Inputs are never changed."""
    floor = parse_ts(cursor_at) if cursor_at is not None else None
    seen = set()
    for r in _ideas(ledger_rows):            # a row's id, and its text's id (the row may predate the id)
        seen.add(r.get("id"))
        if isinstance(r.get("text"), str):
            seen.add(idea_id(r["text"]))
    got = []
    for c in captures or ():
        x = _row(c)
        if x is None or (floor is not None and x[0] <= floor):
            continue
        got.append(x)
    out = []
    for _, row in sorted(got, key=lambda x: x[0]):
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        out.append(row)
    return out


def _result(path, count: int, written: bool, why: str = "", rows=None) -> dict:
    return {"path": None if path is None else str(path), "count": count, "written": written, "why": why,
            "rows": list(rows or [])}


def append(ledger_path, rows: Optional[Iterable], write: bool = False) -> dict:
    """``{path, count, written, why, rows}`` for appending ``rows`` (idea rows only) to the ledger. Dry run
    unless ``write``. No path: nothing, why NO_LEDGER. A write is one os.write with O_APPEND; a file without a
    trailing newline gets one first, and a file this creates is mode 0600. A missing folder is not created."""
    ideas = _ideas(rows)
    if ledger_path is None:
        return _result(None, 0, False, NO_LEDGER)
    path = Path(ledger_path)
    if not ideas:
        return _result(path, 0, False, NOTHING_NEW)
    if not write:
        return _result(path, len(ideas), False, "", ideas)
    if not path.parent.is_dir():
        return _result(path, len(ideas), False, NO_DIR, ideas)
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ideas).encode("utf-8")
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        size = os.fstat(fd).st_size
        if size and os.pread(fd, 1, size - 1) != b"\n":
            body = b"\n" + body
        n = os.write(fd, body)
    finally:
        os.close(fd)
    if n != len(body):
        raise OSError(f"short write to the idea ledger ({n} of {len(body)} bytes)")
    return _result(path, len(ideas), True, "", ideas)


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except (OSError, RuntimeError):
        return False


def run(state, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None, write: bool = False) -> dict:
    """The nightly job: new_rows(captures, ledger, cursor(ledger)) appended to the configured ledger
    (dry run unless ``write``). Reads captures only through StateReader.captures()."""
    reader = StateReader(Path(state))
    path = reader.idea_ledger_path(env, home)
    if path is None:
        return _result(None, 0, False, NO_LEDGER)
    if _same_file(path, reader.path / capture.FILE):
        return _result(path, 0, False, SAME_AS_CAPTURES)
    ledger = reader.idea_ledger_rows(env, home)
    return append(path, new_rows(reader.captures(), ledger, cursor(ledger)), write=write)
