"""Send gate: the one policy every push to Kevin passes through."""
from __future__ import annotations

import hashlib
import re

DAILY_CAP, DEDUP_S = 6, 12 * 3600
ALWAYS = {("limitless", "Wake-up brief"), ("limitless", "Back from nap"), ("limitless", "MIQ for tonight?")}
# 'Asks waiting on you' hit the cap 133x on 11-21 and starved real messages: it becomes one brief line.
FOLD = {"asks"}

# Kanban card ids (t_510c250d) mean nothing to Kevin: plain words only.
_CARD_ID = re.compile(r"[ \t]*\bt_[0-9a-f]{6,12}\b:?")


def scrub(text: str) -> str:
    return _CARD_ID.sub("", text)


def key(title: str, body: str) -> str:
    return hashlib.sha256(f"{scrub(title)}\n{scrub(body)}".encode()).hexdigest()[:16]


def decide(tag: str, title: str, body: str, cls: str, now: float, sent: list, asleep: bool) -> str:
    """Return send | log | fold | hold | duplicate | cap. `sent` = [{t, k}] Telegram sends."""
    if tag in FOLD:
        return "fold"
    if not (cls in ("decision", "critical") or (tag, title) in ALWAYS):
        return "log"
    if cls != "critical" and title != "Back from nap" and asleep:
        return "hold"
    k = key(title, body)
    recent = [s for s in sent if now - s["t"] < 86400]
    if any(s["k"] == k and now - s["t"] < DEDUP_S for s in recent):
        return "duplicate"
    if len(recent) >= DAILY_CAP:
        return "cap"
    return "send"
