"""Voice MIQ: the MIQ answered by voice in a z0live call, read from the call's session events.

    answer_from(transcript, miq) -> Optional[str]

``transcript`` is one call's rows in z0live's session export shape: ``sessions/SESSION_ID.jsonl`` under the
z0live data dir, one JSON object per line, ``{"id", "session_id", "ts", "type", "text", "data"}``
(z0live docs/API.md ``POST /v1/events``; desktop/z0live_desktop/core.py ``export_events`` adds ``id``).
Only two types matter here: ``assistant_transcript`` (what the voice model said) and ``user_transcript``
(what the person said; ``data.final: false`` marks a partial, which is skipped).

The MIQ was asked when an assistant turn holds the MIQ question's words in order (case and punctuation
ignored; a paraphrase is not the MIQ). Its answer is the person's turns after that ask, up to the
assistant's next turn, joined with single spaces. When the MIQ was asked more than once, the latest ask
with an answer wins. None when it was never asked or never answered. Pure: reads its inputs only.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import re
from typing import Optional

ASSISTANT, USER = "assistant_transcript", "user_transcript"
_WORD = re.compile(r"\w+")


def _words(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def _turns(transcript) -> list:
    """(type, text) for the final transcript turns, in ``id`` order when every row has one."""
    if not isinstance(transcript, list):
        return []
    rows = [r for r in transcript if isinstance(r, dict) and r.get("type") in (ASSISTANT, USER)
            and isinstance(r.get("text"), str)]
    if all(isinstance(r.get("id"), int) and not isinstance(r.get("id"), bool) for r in rows):
        rows = sorted(rows, key=lambda r: r["id"])
    out = []
    for r in rows:
        data = r.get("data")
        if r["type"] == USER and isinstance(data, dict) and data.get("final", True) is False:
            continue
        out.append((r["type"], r["text"]))
    return out


def answer_from(transcript, miq) -> Optional[str]:
    """The person's answer to the MIQ in this call, as text; None when it was not asked or not answered."""
    if not isinstance(miq, str) or not _words(miq):
        return None
    question = " " + _words(miq) + " "
    answer, current = None, None
    for kind, text in _turns(transcript) + [(ASSISTANT, "")]:
        if kind == ASSISTANT:
            if current:
                answer = " ".join(current)
            current = [] if question in " " + _words(text) + " " else None
        elif current is not None:
            said = " ".join(text.split())
            if said:
                current.append(said)
    return answer
