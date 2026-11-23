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

    open_miq(state_dir, now) -> Optional[float]
    run(state_dir, now, env=None, dry_run=False) -> {"job", "action", "reason"} | None

The MIQ is open while tonight's MIQ push is in ``jobs-sent.jsonl`` (job ``miq``, sent at most
jobs.MIQ_STALE_S before ``now``) and the mark ``voice-miq.json`` has not captured it; ``open_miq`` returns
that push's send time. ``run`` (limitless-jobs calls it once per pass, after the NOOP export row) reads the
newest z0live session files in config ``voice_miq_sessions`` (z0live's ``sessions`` dir), keeps the rows
from after the push, and hands the first answer it finds (answer_from) to capture.capture as kind
``miq_answer``, source ``z0live``: the one capture store, never a second one. Config ``voice_miq``:
``off`` (the default: no row, nothing read), ``dry_run`` (says in words what it would capture and writes
nothing) or ``write``. A pass that is itself a dry run (``limitless-jobs`` without ``--send``) is a dry run.
After a capture the mark ``{"miq_sent_at", "captured_at"}`` (epoch seconds only, no text, 0600) holds that
MIQ, so a second pass does nothing. Reasons are words only: no digit and never the answer's text. Nothing
here sends, starts or schedules anything. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Mapping, Optional

from . import capture as _capture
from . import jobs, jobs_runner
from .call_brief import write_atomic
from .state_reader import StateReader, config, parse_ts

ASSISTANT, USER = "assistant_transcript", "user_transcript"
CONFIG_KEY, SESSIONS_KEY = "voice_miq", "voice_miq_sessions"
OFF, DRY_RUN, WRITE = "off", "dry_run", "write"
MODES = (OFF, DRY_RUN, WRITE)
MARK = "voice-miq.json"
KIND, SOURCE = "miq_answer", "z0live"
TITLE = "Voice MIQ"
CAPTURED, WOULD, NOTHING = "captured", "would capture", "nothing"
MAX_SESSIONS = 20   # the newest session files by mtime; a call after the push is among them
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


def mode(cfg) -> str:
    """Config ``voice_miq``: off (the default, and any value that is not one of MODES), dry_run or write."""
    v = cfg.get(CONFIG_KEY) if isinstance(cfg, Mapping) else None
    v = v.strip().lower() if isinstance(v, str) else v
    return v if v in MODES else OFF


def _epoch(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def load_mark(state_dir) -> dict:
    """voice-miq.json as ``{"miq_sent_at", "captured_at"}`` (epoch seconds or None); {} when missing or bad."""
    try:
        data = json.loads((Path(state_dir) / MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {"miq_sent_at": _epoch(data.get("miq_sent_at")), "captured_at": _epoch(data.get("captured_at"))}


def _sent_at(state_dir, now: float) -> Optional[float]:
    """Send time of the newest MIQ push at most jobs.MIQ_STALE_S before ``now``; None when there is none."""
    times = [t for t in (_epoch(r.get("t")) for r in StateReader(Path(state_dir)).jobs_sent()
                         if isinstance(r, dict) and r.get("job") == jobs.MIQ.name)
             if t is not None and 0 <= now - t <= jobs.MIQ_STALE_S]
    return max(times) if times else None


def open_miq(state_dir, now: float) -> Optional[float]:
    """The open MIQ's send time: tonight's MIQ push when the mark has not captured it; else None. Reads only."""
    try:
        t = _sent_at(state_dir, now)
    except Exception:  # noqa: BLE001 - unreadable state is no open MIQ, never a traceback
        return None
    return t if t is not None and load_mark(state_dir).get("miq_sent_at") != t else None


def _rows(path: Path) -> list:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue                    # an incomplete tail z0live has not repaired yet
        if isinstance(row, dict):
            out.append(row)
    return out


def sessions_dir(cfg) -> Optional[Path]:
    """Config ``voice_miq_sessions``: z0live's ``sessions`` dir; None when unset."""
    v = cfg.get(SESSIONS_KEY) if isinstance(cfg, Mapping) else None
    return Path(v).expanduser() if isinstance(v, str) and v.strip() else None


def find_answer(sessions: Path, since: float) -> Optional[str]:
    """The MIQ answer in the newest session file that has one, from rows at or after ``since``."""
    files = sorted((p for p in sessions.glob("*.jsonl") if p.is_file()),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_SESSIONS]
    for path in files:
        try:
            rows = _rows(path)
        except OSError:
            continue
        after = [r for r in rows if (parse_ts(r.get("ts")) or 0.0) >= since]
        answer = answer_from(after, jobs_runner.MIQ_QUESTION)
        if answer:
            return answer
    return None


def _write_mark(state_dir, sent_at: float, now: float) -> None:
    write_atomic(Path(state_dir) / MARK, json.dumps({"miq_sent_at": sent_at, "captured_at": now}) + "\n")


def run(state_dir, now: float, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
        dry_run: bool = False) -> Optional[dict]:
    """The voice MIQ's ``{job, action, reason}`` row; None when config ``voice_miq`` is off. Never raises."""
    env = os.environ if env is None else env
    m = mode(config(env, home))
    if m == OFF:
        return None
    try:
        return _run(Path(state_dir), now, env, home, m == DRY_RUN or dry_run)
    except Exception as e:  # noqa: BLE001 - a broken state or session file is one row, never a traceback
        return _row(NOTHING, f"could not read the call ({type(e).__name__}); nothing written")


def _row(action: str, reason: str) -> dict:
    return {"job": TITLE, "action": action, "reason": reason}


def _run(state_dir: Path, now: float, env, home, dry: bool) -> dict:
    if not state_dir.is_dir():
        return _row(NOTHING, "the state dir does not exist; nothing written")
    sent_at = _sent_at(state_dir, now)
    if sent_at is None:
        return _row(NOTHING, "no MIQ is open tonight")
    if load_mark(state_dir).get("miq_sent_at") == sent_at:
        return _row(NOTHING, "tonight's MIQ answer is already captured")
    sessions = sessions_dir(config(env, home))
    if sessions is None:
        return _row(NOTHING, f"the call sessions dir is not configured (config {SESSIONS_KEY})")
    if not sessions.is_dir():
        return _row(NOTHING, "the call sessions dir does not exist")
    answer = find_answer(sessions, sent_at)
    if answer is None:
        return _row(NOTHING, "the MIQ was not answered in a call yet")
    if dry:
        return _row(WOULD, "the MIQ was answered in a call; would capture it as an MIQ answer (dry run: nothing "
                           "written)")
    got = _capture.capture(state_dir, answer, now, source=SOURCE, kind=KIND)
    if not (got.get("value") or {}).get("captured"):
        return _row(NOTHING, "the capture refused the spoken answer (too long or empty); nothing written")
    _write_mark(state_dir, sent_at, now)
    return _row(CAPTURED, "the MIQ was answered in a call; captured as an MIQ answer")
