"""Send gate: the one policy every push to Kevin passes through."""
from __future__ import annotations

import hashlib
import re

from . import decision_window

DAILY_CAP, DEDUP_S = 6, 12 * 3600
ALWAYS = {("limitless", "Wake-up brief"), ("limitless", "Back from nap"), ("limitless", "MIQ for tonight?")}
# 'Asks waiting on you' hit the cap 133x on 11-21 and starved real messages: it becomes one brief line.
FOLD = {"asks"}
# Two senders can word one event differently; the event key lets only the first through.
ONCE_DROP = "already sent for this event"

# Kanban card ids (t_510c250d) mean nothing to Kevin: plain words only.
_CARD_ID = re.compile(r"[ \t]*\bt_[0-9a-f]{6,12}\b:?")
# Every push that goes out ends with one plain line saying why it came now (why_line, outgoing).
WHY_PREFIX = "Why now: "
WHY_FALLBACK = "the send gate let it through"
# The messages that go out whatever their class name the event that sent them.
WHY_ALWAYS = {"Wake-up brief": "you woke up", "Back from nap": "you are back from a nap",
              "MIQ for tonight?": "your wind-down started"}
_DIGIT_PARENS = re.compile(r"\s*\([^()]*\d[^()]*\)")


def scrub(text: str) -> str:
    return _CARD_ID.sub("", text)


def key(title: str, body: str) -> str:
    return hashlib.sha256(f"{scrub(title)}\n{scrub(body)}".encode()).hexdigest()[:16]


def why_reason(cls: str, title: "str | None" = None) -> str:
    """The reason for a push that brings no decision-window reason of its own: the event of an always-sent
    message, else decision_window.decide's reason for an anytime message (critical or not)."""
    if title in WHY_ALWAYS:
        return WHY_ALWAYS[title]
    return decision_window.decide("anytime", None, budget_left=1, asleep=False, critical=cls == "critical").reason


def why_line(reason: "str | None") -> str:
    """``Why now: <reason>``, plain words: no card ids, no digits (a parenthesis or a ``;`` clause that holds
    one is left out), one line. A reason with nothing left is WHY_FALLBACK."""
    text = scrub(reason) if isinstance(reason, str) else ""
    text = _DIGIT_PARENS.sub("", " ".join(text.split()))
    parts = [p.strip(" ,.:") for p in text.split(";")]
    words = "; ".join(p for p in parts if p and not any(c.isdigit() for c in p))
    return WHY_PREFIX + (words or WHY_FALLBACK)


def _is_why(line: str) -> bool:
    return (isinstance(line, str) and line.startswith(WHY_PREFIX) and len(line) > len(WHY_PREFIX)
            and "\n" not in line and not any(c.isdigit() for c in line))


def outgoing(body: str, why: str) -> str:
    """The text that goes out: ``body`` plus the one ``why`` line (why_line) as its last line. A body that
    already ends with a why line is returned as it is, so there is never a second one."""
    if not _is_why(why):
        raise ValueError(f"not a why-now line: {why!r}")
    lines = [ln for ln in (body or "").splitlines() if ln.strip()]
    if lines and _is_why(lines[-1]):
        return body
    return f"{body.rstrip()}\n{why}" if (body or "").strip() else why


def quiet_reason(quiet) -> "str | None":
    """The ``quiet: ...`` reason when ``quiet`` (quiet.active / quiet.check) holds, else None."""
    if isinstance(quiet, tuple) and len(quiet) == 2 and quiet[0] is True:
        return str(quiet[1])
    return None


def quiet_row(now: float, once_key: "str | None") -> dict:
    """The sent.json row for a push dropped by quiet: it claims ``once_key`` (a retry for the same event is
    dropped, not queued) and never counts as a send (daily cap, dedupe)."""
    return {"t": now, "once": once_key, "quiet": True}


def once_sent(sent: list, once_key: "str | None", now: float) -> bool:
    """True when a send in `sent` already claimed `once_key` within the 12 h dedupe window."""
    if not once_key:
        return False
    return any(isinstance(s, dict) and s.get("once") == once_key and isinstance(s.get("t"), (int, float))
               and now - s["t"] < DEDUP_S for s in sent)


def decide(tag: str, title: str, body: str, cls: str, now: float, sent: list, asleep: bool,
           window: "decision_window.JobWindow | None" = None, once_key: "str | None" = None,
           quiet: "tuple | None" = None) -> str:
    """Return send | log | fold | hold | drop | duplicate | cap. `sent` = [{t, k[, once]}] Telegram sends.

    `window` (optional) gates on the job's decision window: hold when its window is not open,
    drop when the peak budget is spent. Without it every result is as before.
    `once_key` (optional) names the event the message is about (e.g. "wake_brief:<event time>"):
    drop (ONCE_DROP) when a send already claimed it within 12 h, whatever its words. Without it
    every result is as before.
    `quiet` (optional) is quiet.check's (held, why): when held, every message that would reach the phone
    is dropped (never held for later), whatever its class: there is no urgent override. Report-only and
    folded messages stay log and fold. Without it every result is as before.
    """
    if tag in FOLD:
        return "fold"
    if not (cls in ("decision", "critical") or (tag, title) in ALWAYS):
        return "log"
    if quiet_reason(quiet) is not None:
        return "drop"   # before the sleep hold: quiet drops, it never queues for the 'Back from nap' message
    if once_sent(sent, once_key, now):
        return "drop"   # before the sleep hold: a held message is replayed later, this one must not be
    if cls != "critical" and title != "Back from nap" and asleep:
        return "hold"
    if window is not None:
        # Sleep was handled above (with its nap exception), so the window check sees asleep=False.
        w = decision_window.decide(window.job_class, window.state, budget_left=window.budget_left,
                                   asleep=False, critical=cls == "critical")
        if w.action != decision_window.DELIVER:
            return w.action
    k = key(title, body)
    recent = [s for s in sent if now - s["t"] < 86400 and not s.get("quiet")]
    if any(s.get("k") == k and now - s["t"] < DEDUP_S for s in recent):
        return "duplicate"
    if len(recent) >= DAILY_CAP:
        return "cap"
    return "send"
