"""limitless_capture: append one line to captures.jsonl in the state dir. The only write this plugin makes.

Capture records a thought and returns. It never starts, schedules or delegates work: triage happens later,
in a review, by the person.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .envelope import envelope, missing

MAX_CHARS = 4000
FILE = "captures.jsonl"


def capture(state: Path, text: str, now: float, source: str = "hermes") -> dict:
    state = Path(state)
    if not isinstance(text, str) or not text.strip():
        return missing("empty capture: nothing recorded")
    if len(text) > MAX_CHARS:
        return missing(f"capture is over {MAX_CHARS} characters: nothing recorded (split it)")
    if not state.is_dir():
        return missing("the state dir does not exist: nothing recorded")
    row = {"at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(), "text": text, "source": source}
    path = state / FILE
    with open(path, "a+b") as f:
        f.seek(0)
        body = f.read()
        lead = b"\n" if body and not body.endswith(b"\n") else b""
        f.write(lead + json.dumps(row, ensure_ascii=False).encode() + b"\n")
    line = body.count(b"\n") + (1 if lead else 0) + 1
    return envelope({"captured": True, "line": line}, "self_report", 0.0)
