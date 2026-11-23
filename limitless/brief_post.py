"""Wake-brief post-processing: the folded 'Asks waiting on you' digest becomes one plain line, and the
ideas bedtime capture saved last night one more ("Saved last night: N ideas"), and the overnight work
queue's landed line (overnight.landed_for: "Overnight: a few done, one failed") one more when given, then
yesterday's work (jobs_runner.brief_flow_ledger: "Yesterday's work: no long blocks.") when known, and
yesterday's naps (jobs_runner.brief_naps: "Naps yesterday: one short nap (phone Sleep mode)") last, when known."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .send_gate import scrub

MAX_AGE_S = 36 * 3600
_ASK = re.compile(r"^A\d+:\s*(.*)$")
_TRAIL_PAREN = re.compile(r"\s*\([^()]*\)\s*$")


def load_asks(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def asks_line(asks: dict | None, now: float) -> str | None:
    if not asks or now - asks.get("at", 0) > MAX_AGE_S:
        return None
    items = [m.group(1) for m in (_ASK.match(ln.strip()) for ln in asks.get("lines", [])) if m]
    if not items:
        return None
    first = _TRAIL_PAREN.sub("", scrub(items[0])).strip()
    if len(first) > 90:
        first = first[:89].rstrip() + "…"
    return f"Asks waiting on you: {len(items)} (first: {first})"


def saved_line(n) -> str | None:
    """"Saved last night: N ideas" for N bedtime captures (bedtime.saved_last_night); None for none."""
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        return None
    return f"Saved last night: {n} idea" + ("" if n == 1 else "s")


def finalize(text: str, asks: dict | None, now: float, saved: int = 0, overnight: str = "", naps: str = "",
             work: str = "") -> str:
    lines = [scrub(text)] + [ln for ln in (asks_line(asks, now), saved_line(saved), scrub(overnight or ""),
                                           scrub(work or ""), scrub(naps or "")) if ln]
    return "\n".join(lines)
