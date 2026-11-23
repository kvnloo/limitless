"""Tier audit: one content-free JSON line per injection, so a weekly check can prove which privacy tier a
cloud model saw.

Tiers (labeler.py): T0 = raw numbers, which never enter a prompt unless the person opted in
(LIMITLESS_RAW_IN_PROMPT=1); T1 = coarse labels made by code or a local model; T2 = a cloud model sees T1
labels only. An injection with no digit is "T1"; one with a digit is "T0". Without the opt-in a digit is a
bug: the text is dropped, not sent, and the line says ``blocked: true``.

    record(event) -> bool   appends {at, hook, tier, lines, digits, opt_in, sha256, blocked}

    shape_event(folded, cut) -> dict   the one row kevin-push writes when message_shape folded or cut a
                                       push: hook ``message_shape``, the two counts, no text and no hash;
                                       not an injection (check leaves it out)

    result_event(glob, replaced) -> dict   the one row result_tier writes when it replaced the numbers in a
                                       listed tool's result: hook ``transform_tool_result:result_tier``, the
                                       t0_tools glob that matched and how many numbers were replaced; no
                                       value, no text and no hash; a filter record, not an injection (check
                                       leaves it out)

Where: $LIMITLESS_AUDIT, else config "audit_path"; off (nothing written) when neither is set. The file is
created 0600 and only ever appended to. ``sha256`` is of the injected text; the text itself is never
written. record never raises: a failed write returns False and the turn goes on.
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

from .state_reader import config, parse_ts

ENV_KEY = "LIMITLESS_AUDIT"
CONFIG_KEY = "audit_path"
T0, T1 = "T0", "T1"
FIELDS = ("at", "hook", "tier", "lines", "digits", "opt_in", "sha256", "blocked")
SHAPE_HOOK = "message_shape"
SHAPE_FIELDS = ("folded", "cut")
RESULT_HOOK = "transform_tool_result:result_tier"


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


def shape_event(folded: int, cut: int, now: Optional[float] = None) -> dict:
    """The content-free row for one push message_shape changed: how many lines were folded and cut, nothing
    else (no text, no hash, no digit of the message)."""
    def n(v):
        return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0
    return {"at": _iso(datetime.now(timezone.utc).timestamp() if now is None else now), "hook": SHAPE_HOOK,
            "tier": T1, "lines": 0, "digits": 0, "opt_in": False, "sha256": "", "blocked": False,
            "folded": n(folded), "cut": n(cut)}


def result_event(glob: str, replaced: int, now: Optional[float] = None) -> dict:
    """The content-free row for one tool result result_tier replaced: the config glob that matched and how
    many numbers became words, nothing else (no value, no text, no hash of the result)."""
    n = replaced if isinstance(replaced, int) and not isinstance(replaced, bool) and replaced > 0 else 0
    return {"at": _iso(datetime.now(timezone.utc).timestamp() if now is None else now), "hook": RESULT_HOOK,
            "tier": T1, "lines": 0, "digits": 0, "opt_in": False, "sha256": "", "blocked": False,
            "glob": str(glob), "replaced": n}


def _clean(ev: Mapping) -> dict:
    """Only the documented fields, with their documented types (a stray ``text`` key is dropped)."""
    row = {k: ev[k] for k in FIELDS if k in ev}
    if ev.get("hook") == SHAPE_HOOK:
        row.update({k: int(ev.get(k) or 0) for k in SHAPE_FIELDS})
    if ev.get("hook") == RESULT_HOOK:
        row.update({"glob": str(ev.get("glob", "")), "replaced": int(ev.get("replaced") or 0)})
    if row.get("tier") not in (T0, T1) or not isinstance(row.get("sha256"), str):
        raise ValueError("not an audit event")
    for k in ("at", "hook"):
        row[k] = str(row.get(k, ""))
    for k in ("lines", "digits"):
        row[k] = int(row.get(k) or 0)
    for k in ("opt_in", "blocked"):
        row[k] = row.get(k) is True
    return row


_HELD = []   # non-empty while inside held(): record writes nothing


@contextmanager
def held():
    """Inside this block record writes nothing and returns False; gate still blocks a digit. For
    limitless-doctor, whose read-only tool calls are a report to the operator, not an injection."""
    _HELD.append(True)
    try:
        yield
    finally:
        _HELD.pop()


def record(ev, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> bool:
    """Append one JSON line for ``ev``; True when written. Off without a path or inside held(); never raises."""
    if _HELD:
        return False
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


def _zero() -> dict:
    return {"injections": 0, "t0_with_opt_in": 0, "t0_without_opt_in": 0, "blocked": 0}


def check(path, since=None) -> dict:
    """Counts of the audit rows at or after ``since`` (epoch seconds or ISO time; None = all). Never raises."""
    out = _zero()
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except (OSError, TypeError, ValueError):
        return out
    floor = parse_ts(since) if since is not None else None
    for ln in text.splitlines():
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("tier") not in (T0, T1) or row.get("hook") in (SHAPE_HOOK, RESULT_HOOK):
            continue
        at = parse_ts(row.get("at")) if isinstance(row.get("at"), str) else None
        if at is None or (floor is not None and at < floor):
            continue
        if row.get("blocked") is True:
            out["blocked"] += 1
            continue
        out["injections"] += 1
        if row["tier"] == T0:
            out["t0_with_opt_in" if row.get("opt_in") is True else "t0_without_opt_in"] += 1
    return out


def words(counts: Mapping) -> list:
    """The counts as plain lines for a person (bin/limitless-tier-audit)."""
    n = counts.get("injections", 0)
    return [f"{n} injection" + ("" if n == 1 else "s"),
            f"{counts.get('t0_with_opt_in', 0)} with raw numbers under the opt-in",
            f"{counts.get('t0_without_opt_in', 0)} with raw numbers without the opt-in",
            f"{counts.get('blocked', 0)} blocked (dropped, not sent)"]
