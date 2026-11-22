"""North-star scorecard: the hand-kept Markdown table -> rows -> a short block for the weekly review.

The table's header is ``| # | Criterion | Status | Evidence (latest) | Weeks green |``. Status is
red, amber or green (anything else reads "unknown"); Weeks green is a whole number. The evidence column
is never read into a row: it may hold private detail and has no place in a summary.
"""
from __future__ import annotations

import re
from typing import List, Optional

from .send_gate import scrub

HEADER = ("#", "criterion", "status", "evidence (latest)", "weeks green")
STATUSES = ("red", "amber", "green")
_SEPARATOR = re.compile(r"^:?-+:?$")
_WHOLE = re.compile(r"^\d+$")


def _cells(line: str) -> Optional[List[str]]:
    """A table line's cells, outer pipes optional; None when the line is not a table line."""
    s = line.strip()
    if "|" not in s:
        return None
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _row(cells: List[str]) -> Optional[dict]:
    if len(cells) != len(HEADER):
        return None
    n, criterion, status, _evidence, weeks = cells
    if not _WHOLE.match(n) or not _WHOLE.match(weeks) or not criterion:
        return None
    status = status.lower()
    return {"n": int(n), "criterion": criterion, "status": status if status in STATUSES else "unknown",
            "weeks_green": int(weeks)}


def parse(md_text: str) -> List[dict]:
    """Rows of the first scorecard table: [{n, criterion, status, weeks_green}]. Malformed rows are skipped;
    no table gives []. The table ends at the first line that is not a table line."""
    rows: List[dict] = []
    inside = False
    for line in (md_text or "").splitlines():
        cells = _cells(line)
        if not inside:
            inside = cells is not None and tuple(c.lower() for c in cells) == HEADER
            continue
        if cells is None:
            break
        if all(_SEPARATOR.match(c) for c in cells):
            continue
        row = _row(cells)
        if row is not None:
            rows.append(row)
    return rows


WEEKS_TO_STOP = 4
MAX_LINES = 5
_RANK = {"red": 0, "amber": 1, "unknown": 2}
_DIGITS = re.compile(r"\d+")


def _name(criterion: str) -> str:
    """Plain words only: no card ids, every digit masked (counts and weeks are the only numbers shown)."""
    name = _DIGITS.sub("#", scrub(criterion))
    name = re.sub(r"\s+", " ", name).strip(" :")
    return name or "unnamed criterion"


def summary(rows: List[dict]) -> List[str]:
    """At most 5 plain-word lines: the counts, the stop-rule state, then up to three criteria furthest
    from green (red, then amber, then unknown; lowest number first). Reports counts only: it never says
    the north star is met. No rows, no lines."""
    if not rows:
        return []
    count = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    lines = [f"{count['green']} green, {count['amber']} amber, {count['red']} red of {len(rows)}"]
    if count["green"] == len(rows):
        weeks = min(WEEKS_TO_STOP, max(0, min(r["weeks_green"] for r in rows)))
        lines.append(f"all green for {weeks} of {WEEKS_TO_STOP} weeks")
    else:
        lines.append("not all green yet")
    behind = sorted((r for r in rows if r["status"] != "green"), key=lambda r: (_RANK[r["status"]], r["n"]))
    lines += [f"{_name(r['criterion'])}: {r['status']}" for r in behind[:MAX_LINES - len(lines)]]
    return lines
