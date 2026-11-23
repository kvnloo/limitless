"""Tier audit: one content-free JSON line per injection, so a weekly check can prove which privacy tier a
cloud model saw.

Tiers (labeler.py): T0 = raw numbers, which never enter a prompt unless the person opted in
(LIMITLESS_RAW_IN_PROMPT=1); T1 = coarse labels made by code or a local model; T2 = a cloud model sees T1
labels only. An injection with no digit is "T1"; one with a digit is "T0". Without the opt-in a digit is a
bug: the text is dropped, not sent, and the line says ``blocked: true``.

    record(event) -> bool   appends {at, hook, tier, lines, digits, opt_in, sha256, blocked}

Where: $LIMITLESS_AUDIT, else config "audit_path"; off (nothing written) when neither is set. The file is
created 0600 and only ever appended to. ``sha256`` is of the injected text; the text itself is never
written. record never raises: a failed write returns False and the turn goes on.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

from .state_reader import config

ENV_KEY = "LIMITLESS_AUDIT"
CONFIG_KEY = "audit_path"
T0, T1 = "T0", "T1"
FIELDS = ("at", "hook", "tier", "lines", "digits", "opt_in", "sha256", "blocked")


def audit_path(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[Path]:
    """$LIMITLESS_AUDIT, else config "audit_path"; None (audit off) by default."""
    env = os.environ if env is None else env
    v = env.get(ENV_KEY) or config(env, home).get(CONFIG_KEY)
    return Path(v).expanduser() if isinstance(v, str) and v.strip() else None


def _iso(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def event(hook: str, text: str, opt_in: bool, now: Optional[float] = None) -> dict:
    """The audit row for one injection of ``text``: counts and a hash, never the text."""
    text = text if isinstance(text, str) else ""
    digits = sum(c.isdigit() for c in text)
    opt_in = opt_in is True
    return {"at": _iso(datetime.now(timezone.utc).timestamp() if now is None else now), "hook": str(hook),
            "tier": T0 if digits else T1, "lines": len(text.splitlines()), "digits": digits, "opt_in": opt_in,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "blocked": bool(digits) and not opt_in}


def _clean(ev: Mapping) -> dict:
    """Only the documented fields, with their documented types (a stray ``text`` key is dropped)."""
    row = {k: ev[k] for k in FIELDS if k in ev}
    if row.get("tier") not in (T0, T1) or not isinstance(row.get("sha256"), str):
        raise ValueError("not an audit event")
    for k in ("at", "hook"):
        row[k] = str(row.get(k, ""))
    for k in ("lines", "digits"):
        row[k] = int(row.get(k) or 0)
    for k in ("opt_in", "blocked"):
        row[k] = row.get(k) is True
    return row


def record(ev, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> bool:
    """Append one JSON line for ``ev``; True when written. Off without a path; never raises."""
    try:
        path = audit_path(env, home)
        if path is None:
            return False
        line = json.dumps(_clean(ev), sort_keys=True) + "\n"
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except Exception:  # noqa: BLE001 - the audit must never break a turn
        return False


def gate(hook: str, text: str, opt_in: bool, env: Optional[Mapping[str, str]] = None,
         home: Optional[Path] = None, now: Optional[float] = None) -> Optional[str]:
    """Record one injection of ``text`` and return what may be sent: ``text``, or None when it has a digit
    without the opt-in (blocked: dropped, never sent). Blocking does not depend on the audit being on."""
    ev = event(hook, text, opt_in, now)
    record(ev, env, home)
    return None if ev["blocked"] else text


def _is_label(v) -> bool:
    return isinstance(v, dict) and "tier" in v and isinstance(v.get("label"), str)


def labels(result) -> list:
    """Every T1 label word in a tool result (the top-level ``label`` and any nested one), in order."""
    out = []

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if k == "label" and _is_label(x):
                    out.append(x["label"])
                else:
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(result)
    return out


def _without_digit_labels(v):
    if isinstance(v, dict):
        return {k: _without_digit_labels(x) for k, x in v.items()
                if not (k == "label" and _is_label(x) and any(c.isdigit() for c in x["label"]))}
    if isinstance(v, list):
        return [_without_digit_labels(x) for x in v]
    return v


def audit_result(hook: str, result, opt_in: bool, env: Optional[Mapping[str, str]] = None,
                 home: Optional[Path] = None, now: Optional[float] = None):
    """Record the labels a tool result carries (one line, over the label words joined by newlines) and return
    the result to send: unchanged, or without its digit-bearing labels when that is blocked. A result with
    no label is not an injection of a label: nothing is recorded."""
    try:
        words = labels(result)
    except Exception:  # noqa: BLE001
        return result
    if not words:
        return result
    if gate(hook, "\n".join(words), opt_in, env, home, now) is None:
        return _without_digit_labels(result)
    return result
