"""The owner's "push via <profile>" reply: it sets kevin-push's sender profile by itself.

    name = parse(text)                                   # the profile a whole message names, or None
    got = ingest(state_dir, replies, now, write=False)   # {"action", "reason", "after"}, words only

When kevin-push's sender profile breaks, the owner is asked in plain words to pick another and answers with one
whole message: ``push via <name>``. ``parse`` takes only that: the message, stripped of surrounding space, is
exactly ``push via <name>`` on one line (any case, spaces or tabs between the words), and the name is one Hermes
resolves under ``profiles/`` (push_sender.PROFILE_ID: lowercase letters, digits, ``-`` and ``_``; the name is
lowercased first, as Hermes stores it). Anything else is ignored, the phrase inside a longer message or a quoted
prompt included.

``ingest`` reads the owner's messages (``(epoch, text)`` pairs, habit_replies.replies_from_hermes_db: role
``user`` in Telegram sessions) after ``read_after`` (the mark's ``after``, else FIRST_READ_S back, so a first run
never acts on an old message). The newest ``push via`` message wins; there is never a fallback to an older one.
Its profile is asked about with push_sender.check (files only, no process): only SET goes on. Then
push_sender.readiness asks the same profile's files whether it can reach Telegram for kevin-push's target (config
``push_to``, presence only, never a value): a definite no (NO_TOKEN: "no bot", NO_CHAT: "no chat") is not
applied, the way a missing profile is not; READY or any ``unknown: ...`` answer (a secret source, a target that is
not Telegram, files that cannot be read) still applies, so an unknown is never a refusal. With ``write``
it writes push_sender.REPLY_FILE (``push-sender.json``: ``{"profile": name, "at": the reply's epoch}``, atomic,
0600, no words), which push_sender.profile reads after ``$KEVIN_PUSH_PROFILE`` and before config
``push_profile``. A profile that does not exist (BROKEN) changes nothing: "that sender profile does not exist".
An ``unknown: ...`` answer from check (no Hermes home known or readable) changes nothing either, and the mark is
not moved past it, so the next pass asks again. The code never picks a sender by itself.

The mark MARK (``push-sender-ingest.json``, atomic, 0600) holds epochs and words only, never a name or a message:
``row_at`` (the runs.jsonl row the job acted on), ``ran_at``, ``mode``, ``action`` (one of ACTIONS), ``after``
(the newest owner message a write pass read) and ``refused_at`` (the epoch of the newest reply that was refused:
missing, no bot or no chat; kept until a later reply is applied, so push_recovery can say so while the outage
is open; refused_at reads it). ``ingest`` returns where ``after`` should move (None: it stays; a
dry run never moves it); sender_ingest_job writes the mark. The config file is never edited. Nothing here sends.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Iterable, Mapping, Optional, Tuple

from . import push_sender

SENDER_FILE = push_sender.REPLY_FILE
MARK = "push-sender-ingest.json"
FIRST_READ_S = 24 * 3600   # with no mark, a first run reads only the last day, so it never acts on an old message
_REPLY = re.compile(r"push[ \t]+via[ \t]+(\S+)", re.IGNORECASE)
NOTHING, WOULD_WRITE, WRITE, MISSING, UNKNOWN = "nothing", "would write", "write", "missing", "unknown"
NO_BOT, NO_CHAT = "no bot", "no chat"      # the named profile exists but cannot reach Telegram (readiness)
ACTIONS = (NOTHING, WOULD_WRITE, WRITE, MISSING, UNKNOWN, NO_BOT, NO_CHAT)
REFUSALS = (MISSING, NO_BOT, NO_CHAT)      # a definite no: the reply was not applied and is not asked about again
MODES = ("dry_run", "write")
SAID = {
    NOTHING: "no new sender reply: the sender profile stays as it is",
    WOULD_WRITE: "would set the sender profile from your reply",
    WRITE: "set the sender profile from your reply",
    MISSING: "that sender profile does not exist: nothing changed",
    UNKNOWN: "the sender profile could not be checked: nothing changed; the next sync tries again",
    NO_BOT: "your reply named a profile with no Telegram bot, so it was not applied",
    NO_CHAT: "your reply named a profile with no Telegram chat to send to, so it was not applied",
}
_READINESS_REFUSAL = {push_sender.NO_TOKEN: NO_BOT, push_sender.NO_CHAT: NO_CHAT, push_sender.MISSING: MISSING}


def parse(text) -> Optional[str]:
    """The profile a whole ``push via <name>`` message names (lowercased), or None for anything else."""
    if not isinstance(text, str):
        return None
    m = _REPLY.fullmatch(text.strip())
    if m is None:
        return None
    name = m.group(1).lower()
    return name if push_sender.PROFILE_ID.match(name) else None


def _epoch(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def load_mark(state_dir) -> dict:
    """MARK as ``{"row_at", "ran_at", "mode", "action", "after"}``; {} when missing or malformed. Epochs or None;
    ``mode`` one of MODES or None; ``action`` one of ACTIONS or None."""
    try:
        data = json.loads((Path(state_dir) / MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {"row_at": _epoch(data.get("row_at")), "ran_at": _epoch(data.get("ran_at")),
            "mode": data.get("mode") if data.get("mode") in MODES else None,
            "action": data.get("action") if data.get("action") in ACTIONS else None,
            "after": _epoch(data.get("after"))}


def _write_json(state_dir, name: str, obj: dict) -> None:
    """``obj`` as ``name`` in the state dir: atomic (a temp file there, then a rename), mode 0600."""
    d = Path(state_dir)
    fd, tmp = tempfile.mkstemp(prefix="." + name + ".", suffix=".tmp", dir=str(d))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, d / name)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def refused_at(state_dir) -> Optional[float]:
    """The mark's ``refused_at``: the epoch of the newest reply that was refused and not followed by an applied
    one; None when there is none, no mark or a broken one. Never raises."""
    try:
        data = json.loads((Path(state_dir) / MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _epoch(data.get("refused_at")) if isinstance(data, dict) else None


def write_mark(state_dir, mark: dict) -> None:
    """MARK in the state dir (atomic, 0600): only the epoch and word fields load_mark and refused_at know."""
    keep = {k: v for k, v in mark.items()
            if k in ("row_at", "ran_at", "mode", "action", "after", "refused_at") and v is not None}
    _write_json(state_dir, MARK, keep)


def write_reply(state_dir, name: str, at: float) -> dict:
    """SENDER_FILE in the state dir (atomic, 0600): ``{"profile": name, "at": epoch}``. Returns it."""
    obj = {"profile": name, "at": float(at)}
    _write_json(state_dir, SENDER_FILE, obj)
    return obj


def read_after(state_dir, now: float) -> float:
    """Epoch seconds after which owner messages are read: the mark's ``after``, else FIRST_READ_S before ``now``."""
    after = load_mark(state_dir).get("after")
    return after if after is not None else float(now) - FIRST_READ_S


def _got(action: str, after: Optional[float], reason: Optional[str] = None, at: Optional[float] = None) -> dict:
    return {"action": action, "reason": reason or SAID[action], "after": after,
            "refused_at": at if action in REFUSALS else None}


def ingest(state_dir, replies: Iterable[Tuple[float, str]], now: float, write: bool = False,
           env: Optional[Mapping[str, str]] = None, hermes_home=None, cfg: Optional[Mapping] = None) -> dict:
    """``{"action", "reason", "after", "refused_at"}`` for the owner's messages after the mark: ``action`` one of
    ACTIONS, ``reason`` in words (never a name, the reply or a digit), ``after`` the epoch the mark's ``after``
    moves to (None: it stays), ``refused_at`` the refused reply's epoch for a REFUSALS action (else None). The
    newest ``push via`` message wins; only a profile push_sender.check calls SET and push_sender.readiness does not
    call NO_TOKEN or NO_CHAT is applied, and only with ``write`` is SENDER_FILE written. ``env`` (default
    os.environ) and ``hermes_home`` locate the Hermes home as for check; ``cfg`` gives kevin-push's target (config
    ``push_to``) for readiness. The env's own $KEVIN_PUSH_PROFILE is not what is asked about: the reply's name is.
    Reads files only: never runs hermes or any process, never reads a secret value."""
    env = os.environ if env is None else env
    after = read_after(state_dir, now)
    msgs = sorted(((float(t), x) for t, x in (replies or ()) if _epoch(t) is not None and after < float(t) <= now),
                  key=lambda r: r[0])
    if not msgs:
        return _got(NOTHING, None)
    newest_read = msgs[-1][0] if write else None
    picks = [(t, n) for t, n in ((t, parse(x)) for t, x in msgs) if n is not None]
    if not picks:
        return _got(NOTHING, newest_read)
    at, name = picks[-1]
    probe = dict(env)
    probe[push_sender.PROFILE_ENV] = name       # ask about the reply's profile, not the env's own
    said = push_sender.check(None, probe, hermes_home)
    if said == push_sender.BROKEN:
        return _got(MISSING, newest_read, at=at)
    if said != push_sender.SET:
        why = said[len(push_sender.UNKNOWN_PREFIX):] if said.startswith(push_sender.UNKNOWN_PREFIX) else said
        return _got(UNKNOWN, None, f"the sender profile could not be checked ({why}): nothing changed; the next "
                                   f"sync tries again")
    refusal = _READINESS_REFUSAL.get(push_sender.readiness(cfg if isinstance(cfg, Mapping) else {}, probe,
                                                           hermes_home))
    if refusal is not None:                     # a definite no; READY and every unknown go on as before
        return _got(refusal, newest_read, at=at)
    if not write:
        return _got(WOULD_WRITE, None)
    write_reply(state_dir, name, at)
    return _got(WRITE, newest_read)
