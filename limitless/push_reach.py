"""Push reach: whether phone pushes can reach the person, in words, for the state card and limitless_status.

    r = reason(cfg, state_dir, today, env)   # SENDER_MISSING / SENDER_NO_BOT / SEND_FAILING / None, words only
    line(r)                                  # "Phone pushes are not reaching you: <reason>", or None
    item(r)                                  # the envelope the card items, limitless_status and the packet carry
    key(cfg, state_dir, env)                 # the stat-only cache-key part (no file is opened)

When kevin-push's sender breaks every push fails and is only logged, so the one channel that would tell the
person is the broken one. The pre_llm_call state card reaches them in any Hermes chat instead. Two facts, both
already on main:

- push_sender.check: BROKEN (the sender profile does not exist) is SENDER_MISSING;
- push_recovery.stage over the same log: UNKNOWN_FAILED (the owner's reply set a profile push_sender.readiness
  could not vouch for, and its confirmation failed to send) is SENDER_NO_BOT, so the card asks for another
  profile instead of only saying the pushes fail;
- delivery_audit.audit over config ``push_log``: ``send_failures`` failing (the last transport attempts of the
  window failed, delivery_audit.SEND_FAIL_RUN in a row) is SEND_FAILING.

The order is REASONS: a broken sender wins, then SENDER_NO_BOT, then SEND_FAILING. Nothing is said when the sender is set and the last transport attempt was
delivered, nor when neither can be told (push_sender unknown, no push log set, unreadable, or no row): unknown
is silent, never alarming. The words never hold a digit, the profile name, the target or a path. It never runs
hermes or any process and never sends. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from datetime import date, tzinfo
from pathlib import Path
from typing import Mapping, Optional

from . import delivery_audit as _delivery, push_sender as _sender
from .envelope import envelope

PREFIX = "Phone pushes are not reaching you: "
SENDER_MISSING = "the sender profile is missing"
SENDER_NO_BOT = ("the profile you named was set but could not send, so it may have no Telegram bot; reply push "
                 "via another profile")    # push_recovery.UNKNOWN_FAILED without its "pushes are failing; "
SEND_FAILING = _delivery.SEND_FAILING          # "the last pushes failed to send"
REASONS = (SENDER_MISSING, SENDER_NO_BOT, SEND_FAILING)   # the order is the precedence
MODALITY = _delivery.MODALITY                  # kevin-push's own log and the profile dir: measured
NONE_KNOWN = "no push outage is known"
_MARKS = (_sender.REPLY_FILE, "push-sender-ingest.json", "sender-confirm.json")   # what push_recovery reads


def _cfg(cfg) -> Mapping:
    return cfg if isinstance(cfg, Mapping) else {}


def reason(cfg: Optional[Mapping], state_dir, today: date, env: Optional[Mapping[str, str]] = None,
           tz: Optional[tzinfo] = None) -> Optional[str]:
    """SENDER_MISSING when push_sender.check is BROKEN; else SENDER_NO_BOT when push_recovery.stage over the push
    log is UNKNOWN_FAILED; else SEND_FAILING when the delivery audit of the push log over the seven local days to
    ``today`` has ``send_failures`` failing; else None. Read-only; never raises (a broken input is unknown, and
    unknown is None)."""
    cfg = _cfg(cfg)
    try:
        if _sender.check(cfg, env) == _sender.BROKEN:
            return SENDER_MISSING
    except Exception:  # noqa: BLE001 - a broken input must not break the card
        pass
    try:
        path = _delivery.log_path(cfg, state_dir)
        got = _delivery.read_log(path) if path is not None else None
        if got and _no_bot(state_dir, got[0], cfg):
            return SENDER_NO_BOT
        if got and _delivery.audit(got[0], today=today, tz=tz)["send_failures"]["failing"]:
            return SEND_FAILING
    except Exception:  # noqa: BLE001
        pass
    return None


def _no_bot(state_dir, rows, cfg: Mapping) -> bool:
    """True when push_recovery.stage over these log rows is UNKNOWN_FAILED (an open outage only, so its clock
    argument is never read)."""
    from . import push_recovery     # late: push_recovery reads the sender and recap jobs' marks
    try:
        return push_recovery.stage(state_dir, rows, cfg, 0.0)[1] == push_recovery.UNKNOWN_FAILED
    except Exception:  # noqa: BLE001
        return False


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
    """What ``reason`` depends on, from stats alone: push_sender.check's words (directory checks only), the
    push log's mtime and the mtimes of the reply and mark files push_recovery reads (push-sender.json, the sender
    ingest and sender confirm marks). The card caches its line under this (and the day), so a turn opens no extra
    file."""
    cfg = _cfg(cfg)
    try:
        words = _sender.check(cfg, env)
    except Exception:  # noqa: BLE001
        words = None
    try:
        path = _delivery.log_path(cfg, state_dir)
    except Exception:  # noqa: BLE001
        path = None
    marks = tuple(_mtime(Path(state_dir) / n) for n in _MARKS) if state_dir is not None else ()
    return (words, None if path is None else str(path), _mtime(path), marks)
