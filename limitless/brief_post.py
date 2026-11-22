"""Wake-brief post-processing: the folded 'Asks waiting on you' digest becomes one plain line."""
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


def finalize(text: str, asks: dict | None, now: float) -> str:
    out = scrub(text)
    line = asks_line(asks, now)
    return f"{out}\n{line}" if line else out
