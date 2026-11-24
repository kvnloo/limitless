"""The owner's "restore <profile>" reply: recorded for the operator and acknowledged, never acted on.

    name = parse(text)                                          # the profile a whole message names, or None
    got = ingest(state_dir, replies, now, after, write=False)   # {"action", "request"}
    req = load(state_dir)                                       # {"profile", "at", "seen_at"} or None
    asked(state_dir, cfg, since, env=None, hermes_home=None)    # True while the request still counts

When Hermes deleted kevin-push's sender profile (push_sender.tombstoned) the state card asks the owner to reply
``restore <name>``. Restoring a profile recreates a Hermes profile and its gateway, an operator action, so the plugin
never does it: it only records that it was asked and says so.

``parse`` takes only a whole message, the way sender_reply.parse takes ``push via``: stripped of surrounding space it
is exactly ``restore <name>`` on one line (any case, spaces or tabs between the words) with a name Hermes resolves
(push_sender.PROFILE_ID, lowercased first). Anything else is ignored, the phrase inside a longer message included.

``ingest`` gets the same owner messages the sender ingest job read (``(epoch, text)`` pairs after the same mark
``after``) and takes the newest ``restore`` message; there is never a fallback to an older one. It counts only when
the name is the current sender (push_sender.profile) and that sender is tombstoned; anything else is NOTHING and
nothing is written. With ``write`` it writes REQUEST_FILE (``restore-request.json``: ``{"profile": name, "at": the
message's epoch, "seen_at": now}``, atomic, 0600); without it the action is WOULD_RECORD and nothing is written.

``asked`` is what the card, push_recovery and the doctor read: True only while the request names the current sender,
that sender is still tombstoned and the request's ``at`` is at or after ``since`` (the open outage's first failed
row). When the profile is live again the request is stale and every surface says what it said before. The file is
never removed. Files only: never runs hermes or any process, never touches the Hermes home, never sends. Stdlib only,
Python 3.9+.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Iterable, Mapping, Optional, Tuple

from . import push_sender

REQUEST_FILE = "restore-request.json"
_REPLY = re.compile(r"restore[ \t]+(\S+)", re.IGNORECASE)
NOTHING, WOULD_RECORD, RECORD = "nothing", "would record", "record"
SAID = {
    WOULD_RECORD: "would record your restore request for the operator",
    RECORD: "recorded your restore request; the operator restores the profile",
}


def parse(text) -> Optional[str]:
    """The profile a whole ``restore <name>`` message names (lowercased), or None for anything else."""
    if not isinstance(text, str):
        return None
    m = _REPLY.fullmatch(text.strip())
    if m is None:
        return None
    name = m.group(1).lower()
    return name if push_sender.PROFILE_ID.match(name) else None


def _epoch(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _sender(cfg, env, state_dir) -> Optional[str]:
    try:
        return push_sender.profile(cfg if isinstance(cfg, Mapping) else {}, env, state_dir).lower()
    except Exception:  # noqa: BLE001 - unknown is not the sender
        return None


def _counts(name: str, state_dir, cfg, env, hermes_home) -> bool:
    """True when ``name`` is the current sender and Hermes has deleted it (push_sender.tombstoned)."""
    if name != _sender(cfg, env, state_dir):
        return False
    try:
        return push_sender.tombstoned(cfg if isinstance(cfg, Mapping) else {}, env, hermes_home)
    except Exception:  # noqa: BLE001
        return False


def ingest(state_dir, replies: Iterable[Tuple[float, str]], now: float, after: float, write: bool = False,
           cfg: Optional[Mapping] = None, env: Optional[Mapping[str, str]] = None, hermes_home=None) -> dict:
    """``{"action", "request"}``: ``action`` NOTHING, WOULD_RECORD or RECORD; ``request`` the dict written (RECORD)
    or that would be (WOULD_RECORD), else None. The newest whole ``restore <name>`` message in ``after < t <= now``
    counts only for the tombstoned current sender; REQUEST_FILE is written only with ``write``."""
    picks = sorted((float(t), n) for t, n in ((t, parse(x)) for t, x in (replies or ())
                                               if _epoch(t) is not None and after < float(t) <= now)
                   if n is not None)
    if not picks:
        return {"action": NOTHING, "request": None}
    at, name = picks[-1]
    if not _counts(name, state_dir, cfg, env, hermes_home):
        return {"action": NOTHING, "request": None}
    req = {"profile": name, "at": at, "seen_at": float(now)}
    if not write:
        return {"action": WOULD_RECORD, "request": req}
    from .sender_reply import _write_json     # the same atomic 0600 write as push-sender.json
    _write_json(state_dir, REQUEST_FILE, req)
    return {"action": RECORD, "request": req}


def load(state_dir) -> Optional[dict]:
    """REQUEST_FILE as ``{"profile", "at", "seen_at"}``; None when missing, unreadable or malformed. Never raises."""
    if state_dir is None:
        return None
    try:
        data = json.loads((Path(state_dir) / REQUEST_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    name, at = data.get("profile"), _epoch(data.get("at"))
    if not isinstance(name, str) or not push_sender.PROFILE_ID.match(name) or at is None:
        return None
    return {"profile": name, "at": at, "seen_at": _epoch(data.get("seen_at"))}


def asked(state_dir, cfg: Optional[Mapping], since: Optional[float], env: Optional[Mapping[str, str]] = None,
          hermes_home=None) -> bool:
    """True while a recorded request names the current sender, that sender is still tombstoned and the request
    came at or after ``since`` (None: never). Read-only; never raises."""
    try:
        req = load(state_dir)
        if req is None or since is None or req["at"] < since:
            return False
        return _counts(req["profile"], state_dir, cfg, env, hermes_home)
    except Exception:  # noqa: BLE001 - a broken input keeps today's words
        return False
