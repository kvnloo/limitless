"""held.jsonl: the pushes Sleep mode held for the "Back from nap" message, each message kept once.

Senders retry every pass (the wake brief retries every sync until it is delivered), so one night can hold one
message many times. ``add`` keeps at most one row per message: rows with the same ``--once`` key are one
message, else rows with the same send-gate dedupe key (``send_gate.key`` of the title and the body without its
why-now line). The newest copy replaces the older one (its text may be fresher) and the rows stay in order of
their newest hold time. A different message is never dropped. The file is replaced whole (temp file in the
same directory, mode 0600, ``os.replace``) under an advisory lock, so two senders holding at once lose nothing.

``rows`` is the reader: it lists each held message once, also from a file an older version wrote with repeats.
A line that is not a held row (not JSON, not an object, no string title and body) is skipped by ``rows`` and
kept as it is by ``add``: nothing raises, and nothing the reader cannot read is thrown away.
"""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from . import send_gate as g

try:
    import fcntl
except ImportError:  # pragma: no cover - not on POSIX: no lock, the replace is still atomic
    fcntl = None

LOCK_NAME = "held.jsonl.lock"


def without_why(body: str) -> str:
    """``body`` without trailing why-now lines (send_gate's dedupe key is the message without it)."""
    lines = (body or "").splitlines()
    while lines and (not lines[-1].strip() or g._is_why(lines[-1].strip())):
        lines.pop()
    return "\n".join(lines)


def hold_key(title: str, body: str, once: "str | None" = None) -> str:
    """One message, one key: ``once:<KEY>`` when a --once key is given, else ``k:<send_gate.key>``."""
    if isinstance(once, str) and once.strip():
        return "once:" + once.strip()
    return "k:" + g.key(title or "", without_why(body or ""))


def _parse(line: str):
    """The held row on ``line``, or None when it is not one."""
    try:
        row = json.loads(line)
    except ValueError:
        return None
    if not isinstance(row, dict) or not isinstance(row.get("title"), str) or not isinstance(row.get("body"), str):
        return None
    return row


def _row_key(row: dict) -> str:
    return row["k"] if isinstance(row.get("k"), str) and row["k"] else hold_key(row["title"], row["body"],
                                                                                row.get("once"))


def _at(row: dict) -> float:
    at = row.get("at")
    return float(at) if isinstance(at, (int, float)) and not isinstance(at, bool) else float("-inf")


def collapse(rows: list) -> list:
    """One row per message: the last copy of each in file order wins, then a stable sort by hold time."""
    by_key = {}
    for row in rows:
        k = _row_key(row)
        by_key.pop(k, None)
        by_key[k] = row
    return sorted(by_key.values(), key=_at)


def _lines(path: Path) -> list:
    try:
        return Path(path).read_text(errors="replace").splitlines()
    except (OSError, ValueError):
        return []


def rows(path) -> list:
    """Each held message once (newest copy), oldest hold first. Read-only; a missing file is []."""
    return collapse([r for r in (_parse(ln) for ln in _lines(path)) if r is not None])


@contextmanager
def _locked(path: Path):
    if fcntl is None:
        yield
        return
    fd = os.open(str(path.with_name(LOCK_NAME)), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def add(path, row: dict, once: "str | None" = None) -> None:
    """Hold ``row`` ({at, tag, title, body}) in ``path``: it replaces any older copy of the same message."""
    path = Path(path)
    row = dict(row)
    if isinstance(once, str) and once.strip():
        row["once"] = once.strip()
    row["k"] = hold_key(row.get("title", ""), row.get("body", ""), once)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(path):
        kept, held = [], []
        for ln in _lines(path):
            r = _parse(ln)
            if r is None:
                if ln.strip():
                    kept.append(ln)          # not a held row: kept as it is, never dropped
            else:
                held.append(r)
        out = kept + [json.dumps(r) for r in collapse(held + [row])]
        fd, tmp = tempfile.mkstemp(prefix=".held-", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w") as f:
                f.write("".join(ln + "\n" for ln in out))
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
