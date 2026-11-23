"""limitless_capture: append one line to captures.jsonl in the state dir. The only write this plugin makes.

Capture records a thought and returns. It never starts, schedules or delegates work: triage happens later,
in a review, by the person.

A row is ``{"at", "text", "source"}``; ``kind`` (one of KINDS) is added only when given, and ``unknowns`` (a
list of the person's own phrases, verbatim) only when there are any. An explain-back answer (explain_back.reply)
is ``kind: "explain_back"``; like every capture it reaches the idea ledger when one is set. An MIQ answered by
voice in a z0live call (voice_miq.run) is ``kind: "miq_answer"``, source ``"z0live"``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .envelope import envelope, missing

MAX_CHARS = 4000
FILE = "captures.jsonl"
KINDS = ("explain_back", "miq_answer")


def capture(state: Path, text: str, now: float, source: str = "hermes", kind=None, unknowns=None) -> dict:
    state = Path(state)
    if not isinstance(text, str) or not text.strip():
        return missing("empty capture: nothing recorded")
    if len(text) > MAX_CHARS:
        return missing(f"capture is over {MAX_CHARS} characters: nothing recorded (split it)")
    if kind is not None and kind not in KINDS:
        return missing(f"unknown capture kind: nothing recorded (kinds: {', '.join(KINDS)})")
    if not state.is_dir():
        return missing("the state dir does not exist: nothing recorded")
    row = {"at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(), "text": text, "source": source}
    if kind is not None:
        row["kind"] = kind
    extra = [u for u in unknowns or () if isinstance(u, str) and u.strip()]
    if extra:
        row["unknowns"] = extra
    path = state / FILE
    with open(path, "a+b") as f:
        f.seek(0)
        body = f.read()
        lead = b"\n" if body and not body.endswith(b"\n") else b""
        f.write(lead + json.dumps(row, ensure_ascii=False).encode() + b"\n")
    line = body.count(b"\n") + (1 if lead else 0) + 1
    return envelope({"captured": True, "line": line}, "self_report", 0.0)
