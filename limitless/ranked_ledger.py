"""The ranked ledger's only two writers: an agent's evidence row, and the owner's drop by reply.

    row = add(path, item_id, status, evidence, write=False)       # one agent row: open | built | verified
    got = ingest(state_dir, path, replies, now, write=False)      # "drop: <id>[, <id>...]" from the owner

The ledger is the private JSONL file scorecard row ten reads (scorecard.ledger_path: $LIMITLESS_RANKED_LEDGER, else
config ``ranked_ledger``; the repo ships none). One JSON object per line, ``{"id", "status", "by", "evidence"}``;
the newest row per id wins. Rows are only ever appended: the file is opened O_APPEND, created mode 0600 (an
existing file is set to 0600), held under an exclusive flock for the write, and no old row is rewritten.

An agent row has ``by: "agent"`` and a status in AGENT_STATUSES; ``verified`` needs a non-empty evidence string,
and ``dropped`` is never an agent's: only the owner drops. An agent cannot bring back an item whose newest row is
the owner's drop. A drop row is ``{"id", "status": "dropped", "by": scorecard.OWNER, "evidence": "owner reply"}``,
appended only for an id the ledger already has, from a whole owner message ``drop: <id>[, <id>...]`` read from
the Hermes session DB (habit_replies.replies_from_hermes_db, read-only) after the mark ``ranked-drops.json``
(epoch seconds only, 0600, atomic). Every drop message after the mark counts; any other message does nothing.
Dry run unless written. Output lines are words only: never an id, evidence text or a digit. Nothing here sends.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Tuple

from . import scorecard

AGENT = "agent"
AGENT_STATUSES = ("open", "built", "verified")
DROPPED = "dropped"
DROP_EVIDENCE = "owner reply"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
NO_LEDGER = "no ranked ledger set (LIMITLESS_RANKED_LEDGER or config \"ranked_ledger\")"


class Refused(ValueError):
    """A row this writer will not append; the message is words only (no id, no evidence)."""


def valid_id(item_id) -> bool:
    """A ledger id: a letter or digit, then letters, digits, dot, underscore or dash; at most eighty in all."""
    return isinstance(item_id, str) and ID_RE.match(item_id) is not None and "\n" not in item_id


def agent_row(item_id, status, evidence=None) -> dict:
    """The one row an agent may append, or Refused: a valid id, a status in AGENT_STATUSES (never dropped), and
    for verified a non-empty evidence string."""
    if status == DROPPED:
        raise Refused("dropped is refused: only the owner drops, by reply")
    if status not in AGENT_STATUSES:
        raise Refused("the status must be open, built or verified")
    if not valid_id(item_id):
        raise Refused("the id must be letters, digits, dot, underscore or dash, at most eighty, not starting "
                      "with a dot, underscore or dash")
    ev = evidence.strip() if isinstance(evidence, str) else ""
    if status == "verified" and not ev:
        raise Refused("verified needs a non-empty evidence string (--evidence)")
    return {"id": item_id, "status": status, "by": AGENT, "evidence": ev}


def read(path) -> Optional[str]:
    """The ledger's text, or None when it is missing or cannot be read."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def newest(path) -> dict:
    """The newest valid row per id (scorecard's own rule); {} when the ledger is missing or unreadable."""
    return scorecard._ledger_rows(read(path) or "")


def owner_dropped(row) -> bool:
    return isinstance(row, Mapping) and row.get("status") == DROPPED and row.get("by") == scorecard.OWNER


def append(path, rows: List[dict]) -> int:
    """Append ``rows``, one JSON object per line, under an exclusive flock; mode 0600. A torn last line (no
    newline) is left as it is and the first new row starts on a line of its own. Returns the rows appended."""
    if not rows:
        return 0
    data = "".join(json.dumps(r, ensure_ascii=False, sort_keys=False) + "\n" for r in rows).encode("utf-8")
    fd = os.open(str(path), os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.fchmod(fd, 0o600)
            size = os.fstat(fd).st_size
            if size and os.pread(fd, 1, size - 1) != b"\n":
                data = b"\n" + data
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
    return len(rows)


def add(path, item_id, status, evidence=None, write: bool = False) -> dict:
    """One agent row (agent_row), appended when ``write``; Refused when the owner dropped this item already."""
    row = agent_row(item_id, status, evidence)
    if owner_dropped(newest(path).get(item_id)):
        raise Refused("the owner dropped this item: an agent cannot bring it back")
    if write:
        append(path, [row])
    return row


# --- list: the counts row ten reads, in words -------------------------------------------------------------

COUNT_WORDS = (("verified", "verified with evidence"), ("owner_dropped", "dropped by the owner"),
               ("open", "open or built"),
               ("not_counted", "not counted (verified without evidence, or dropped by someone else)"))
RAW_KEYS = scorecard.TOP_RAW_KEYS


def summary(state_dir, cfg: Mapping, env: Optional[Mapping[str, str]] = None) -> Tuple[str, Optional[dict]]:
    """(row ten's label, its counts or None) through scorecard._top_measured, the one rule for both."""
    label, _goal, audit = scorecard._top_measured(state_dir, cfg or {}, 0.0, None, env, None)
    return label, ({k: audit[k] for k in RAW_KEYS} if audit else None)


def list_lines(label: str, counts: Optional[dict]) -> List[str]:
    """``ranked ledger: <label>`` then one line per count as a share in words (all, most, some, few, none)."""
    out = [f"ranked ledger: {label}"]
    if counts:
        out += [f"{words}: {scorecard.share_word(counts[k], counts['items'])}" for k, words in COUNT_WORDS]
    return out
