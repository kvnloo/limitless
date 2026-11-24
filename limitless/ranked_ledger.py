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
        raise Refused("dropped: only the owner drops, by reply")
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


def skipped_lines(text: str) -> int:
    """How many non-blank lines are not a valid row (scorecard._ledger_rows skips them: torn or another shape)."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return sum(1 for ln in lines if not scorecard._ledger_rows(ln))


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


# --- owner drops by reply ---------------------------------------------------------------------------------

MARK = "ranked-drops.json"
FIRST_READ_S = 24 * 3600   # with no mark, a first run reads only the last day, so it never acts on an old message
_DROP = re.compile(r"^drop\s*:(.*)$", re.IGNORECASE)
WRITE, WOULD_WRITE, IGNORE, NOTHING = "write", "would write", "ignore", "nothing"
_NUMBER_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                 "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
                 "twenty")


def count_words(n: int) -> str:
    """A count as a word: no, one ... twenty, else "more than twenty". Never a digit."""
    return _NUMBER_WORDS[n] if 0 <= n < len(_NUMBER_WORDS) else "more than twenty"


def parse_drop(text) -> Optional[tuple]:
    """The ids a whole message ``drop: <id>[, <id>...]`` names (any case for ``drop``, one line, ids comma
    separated, trimmed, de-duplicated in order), or None for anything else: another word, a second line, an
    empty item or an id that is not valid_id. None means the message does nothing."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    if "\n" in s or "\r" in s:
        return None
    m = _DROP.match(s)
    if m is None:
        return None
    ids = [p.strip() for p in m.group(1).split(",")]
    if not ids or any(not valid_id(i) for i in ids):
        return None
    out = []
    for i in ids:
        if i not in out:
            out.append(i)
    return tuple(out)


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def load_mark(state_dir) -> Optional[float]:
    """The mark's ``after`` (epoch seconds of the last owner message read), or None when missing or malformed."""
    try:
        data = json.loads((Path(state_dir) / MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    v = data.get("after") if isinstance(data, dict) else None
    return float(v) if _number(v) else None


def write_mark(state_dir, after: float) -> None:
    """``{"after": epoch}`` in the state dir, atomic (a temp file there, then a rename), mode 0600."""
    d = Path(state_dir)
    fd, tmp = tempfile.mkstemp(prefix="." + MARK + ".", suffix=".tmp", dir=str(d))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps({"after": float(after)}) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, d / MARK)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_after(state_dir, now: float) -> float:
    """Epoch seconds after which owner messages are read: the mark, else FIRST_READ_S before ``now``."""
    after = load_mark(state_dir)
    return after if after is not None else float(now) - FIRST_READ_S


def _row(action: str, reason: str, drops: int = 0, unknown: int = 0, already: int = 0) -> dict:
    return {"action": action, "reason": reason, "drops": drops, "unknown": unknown, "already": already}


def ingest(state_dir, path, replies: Iterable[Tuple[float, str]], now: float, write: bool = False) -> dict:
    """``{"rows", "appended", "mark"}``: one row per owner message after the mark (or one ``nothing`` row), in
    words and counts, never an id. A drop message appends one owner drop row per id the ledger already has
    (an unknown id is ignored and counted; an id the owner already dropped is counted and not appended again).
    With ``write`` the rows are appended, then the mark moves to the newest message read; a dry run writes
    nothing. ``mark`` is the epoch the mark is (or would be) set to, None when it stays."""
    after = read_after(state_dir, now)
    msgs = sorted(((float(t), x) for t, x in (replies or ()) if _number(t) and after < float(t) <= now),
                  key=lambda r: r[0])
    if not msgs:
        return {"rows": [_row(NOTHING, "no new owner message: the ranked ledger stays as it is")], "appended": 0,
                "mark": None}
    known = newest(path)
    rows, new, queued = [], [], set()
    for _t, text in msgs:
        ids = parse_drop(text)
        if ids is None:
            rows.append(_row(IGNORE, "not a drop reply: changes nothing"))
            continue
        drops = [i for i in ids if i in known and not owner_dropped(known[i]) and i not in queued]
        unknown = sum(1 for i in ids if i not in known)
        already = len(ids) - unknown - len(drops)
        queued.update(drops)
        new += [{"id": i, "status": DROPPED, "by": scorecard.OWNER, "evidence": DROP_EVIDENCE} for i in drops]
        action = (WRITE if write else WOULD_WRITE) if drops else IGNORE
        rows.append(_row(action, "a drop reply from the owner", len(drops), unknown, already))
    mark = msgs[-1][0]
    if write:
        append(path, new)
        write_mark(state_dir, mark)
    return {"rows": rows, "appended": len(new) if write else 0, "mark": mark, "would_append": len(new)}


def ingest_lines(got: dict, written: bool) -> List[str]:
    """The CLI's lines for an ingest() result: one per message, then the total, then the dry-run note."""
    out = []
    for r in got["rows"]:
        line = f"{r['action']}: {r['reason']}"
        if r["reason"] == "a drop reply from the owner":
            line += (f": {count_words(r['drops'])} to drop, {count_words(r['unknown'])} unknown ignored, "
                     f"{count_words(r['already'])} already dropped")
        out.append(line)
    n = got.get("would_append", 0)
    if got["mark"] is not None:
        out.append(f"{'appended' if written else 'would append'} {count_words(n)} owner drop "
                   f"row{'' if n == 1 else 's'}")
    if not written:
        out.append(f"dry run: nothing written (--write appends to the ranked ledger and moves {MARK})")
    return out
