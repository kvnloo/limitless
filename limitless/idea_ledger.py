"""Idea ledger: the one official record every idea lands in, appended by a job, never rewritten.

    rows = new_rows(captures, ledger_rows, cursor)   # the captures not yet in the ledger, as idea rows
    out = append(ledger_path, rows, write=False)    # dry run by default

Ideas arrive as quick captures (limitless_capture) and as plain messages saved by bedtime capture; both are
written by capture.py to captures.jsonl, so StateReader.captures() is the only input. Message stores are never
read for content (owner_messages reads timestamps only). An idea row is
``{"kind": "idea", "id", "at", "text", "source", "status": "new"}``: ``at`` and ``source`` as captured, ``id``
``idea_`` plus a short sha256 of the normalised text (NFKC, case-folded, whitespace collapsed). The same
normalised text is one idea: a re-run, or the same thought captured twice, appends nothing.

``cursor`` (cursor(ledger_rows): the newest idea ``at`` already in the ledger) skips captures at or before it,
so an idea the person removed from the ledger in a review is not appended again.

The code never triages, ranks or starts anything: every row it writes is ``status: "new"``; the person changes
a status by hand in a review. Existing rows are never rewritten or reordered. ``new_rows`` and ``cursor`` are
pure. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Iterable, Optional

from .state_reader import parse_ts

KIND, NEW = "idea", "new"
UNKNOWN_SOURCE = "unknown"
ID_PREFIX, ID_HEX = "idea_", 16
_WS = re.compile(r"\s+")


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
