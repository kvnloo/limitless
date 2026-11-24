"""Push reach: whether phone pushes can reach the person, in words, for the state card and limitless_status.

    r = reason(cfg, state_dir, today, env)   # SENDER_MISSING / SEND_FAILING / None, words only
    line(r)                                  # "Phone pushes are not reaching you: <reason>", or None
    item(r)                                  # the envelope the card items, limitless_status and the packet carry
    key(cfg, state_dir, env)                 # the stat-only cache-key part (no file is opened)

When kevin-push's sender breaks every push fails and is only logged, so the one channel that would tell the
person is the broken one. The pre_llm_call state card reaches them in any Hermes chat instead. Two facts, both
already on main:

- push_sender.check: BROKEN (the sender profile does not exist) is SENDER_MISSING;
- delivery_audit.audit over config ``push_log``: ``send_failures`` failing (the last transport attempts of the
  window failed, delivery_audit.SEND_FAIL_RUN in a row) is SEND_FAILING.

A broken sender wins when both hold. Nothing is said when the sender is set and the last transport attempt was
delivered, nor when neither can be told (push_sender unknown, no push log set, unreadable, or no row): unknown
is silent, never alarming. The words never hold a digit, the profile name, the target or a path. It never runs
hermes or any process and never sends. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from datetime import date, tzinfo
from typing import Mapping, Optional

from . import delivery_audit as _delivery, push_sender as _sender
from .envelope import envelope

PREFIX = "Phone pushes are not reaching you: "
SENDER_MISSING = "the sender profile is missing"
SEND_FAILING = _delivery.SEND_FAILING          # "the last pushes failed to send"
REASONS = (SENDER_MISSING, SEND_FAILING)       # the order is the precedence
MODALITY = _delivery.MODALITY                  # kevin-push's own log and the profile dir: measured
NONE_KNOWN = "no push outage is known"


def _cfg(cfg) -> Mapping:
    return cfg if isinstance(cfg, Mapping) else {}


def reason(cfg: Optional[Mapping], state_dir, today: date, env: Optional[Mapping[str, str]] = None,
           tz: Optional[tzinfo] = None) -> Optional[str]:
    """SENDER_MISSING when push_sender.check is BROKEN; else SEND_FAILING when the delivery audit of the push
    log over the seven local days to ``today`` has ``send_failures`` failing; else None. Read-only; never
    raises (a broken input is unknown, and unknown is None)."""
    cfg = _cfg(cfg)
    try:
        if _sender.check(cfg, env) == _sender.BROKEN:
            return SENDER_MISSING
    except Exception:  # noqa: BLE001 - a broken input must not break the card
        pass
    try:
        path = _delivery.log_path(cfg, state_dir)
        got = _delivery.read_log(path) if path is not None else None
        if got and _delivery.audit(got[0], today=today, tz=tz)["send_failures"]["failing"]:
            return SEND_FAILING
    except Exception:  # noqa: BLE001
        pass
    return None


def line(r: Optional[str]) -> Optional[str]:
    """The card line for a ``reason``; None for no reason (or anything that is not one of REASONS)."""
    return PREFIX + r if r in REASONS else None


def item(r: Optional[str]) -> dict:
    """The envelope for a ``reason``: value the line's words, modality measured, age_h None (so evidence_tier
    is the envelope's ``stale``: no single row dates it); value None with NONE_KNOWN when there is no line."""
    words = line(r)
    return envelope(words, MODALITY, None, reason=None if words else NONE_KNOWN)


def _mtime(path) -> Optional[int]:
    try:
        return None if path is None else path.stat().st_mtime_ns
    except OSError:
        return None


def key(cfg: Optional[Mapping], state_dir, env: Optional[Mapping[str, str]] = None) -> tuple:
    """What ``reason`` depends on, from stats alone: push_sender.check's words (directory checks only) and the
    push log's mtime. The card caches its line under this (and the day), so a turn opens no extra file."""
    cfg = _cfg(cfg)
    try:
        words = _sender.check(cfg, env)
    except Exception:  # noqa: BLE001
        words = None
    try:
        path = _delivery.log_path(cfg, state_dir)
    except Exception:  # noqa: BLE001
        path = None
    return (words, None if path is None else str(path), _mtime(path))
