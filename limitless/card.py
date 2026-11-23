"""Today's state card: the limitless_state tool and the pre_llm_call hook.

Privacy tier T2 (default): the card carries coarse labels only ("sleep short (proxy)", "readiness low"),
made at the source by the T1 labeler (labeler.py: rules, or an optional local model), so its lines never
hold a raw value. Every digit left in it is masked as a second guard (MASK_DIGITS). LIMITLESS_RAW_IN_PROMPT=1
opts in to raw numbers. Labels describe one imported or proxy value; nothing here computes a score.
The hook's card is cached until the window class, a card input file's mtime, the date, the raw flag or the
owner-message label (tools.owner_message: one short read-only probe of each owner session DB per turn) changes.
Each injection goes through tier_audit.gate: one content-free audit line, and a card with a digit but no
opt-in is dropped, not sent.
"""
from __future__ import annotations

import os
import re
import time
from datetime import date
from typing import Callable, Mapping, Optional

from . import labeler as _labeler
from . import tier_audit, tools
from .envelope import STALE_H, envelope, missing
from .state_reader import StateReader, parse_ts, state_dir
from .window import window

MAX_LINES = 6
ASKS_MAX_AGE_H = 36.0
CARD_FILES = ("inputs.json", "digests.jsonl", "habit.json", "asks-latest.json")
_WEAKEST_LAST = ("measured", "messages", "imported", "self_report", "proxy")
MASK_DIGITS = True  # the second guard: lines are built from T1 labels first


def sleep_label(hours: float) -> str:
    return _labeler.rule_label("sleep_h", hours)


def readiness_label(v: float) -> str:
    return _labeler.rule_label("readiness", v)


METRICS = (("sleep", "sleep_h", " h"), ("readiness", "readiness", ""))


def _t1(lab: Callable, kind: str, value, modality) -> dict:
    """The labeler's answer, kept only if it is one of the kind's labels (else unknown, never a guess)."""
    try:
        out = lab(kind, value, modality)
        word = out.get("label") if isinstance(out, dict) else None
    except Exception:  # a broken labeler must not break the card
        word = None
    ok = isinstance(word, str) and word in _labeler.ALLOWED.get(kind, ())
    return _labeler.t1(word if ok else _labeler.UNKNOWN, modality)


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _metric_items(reader: StateReader, now: float, raw: bool, lab: Callable):
    d = reader.latest_digest()
    t = parse_ts((d or {}).get("at"))
    age_h = None if t is None else max(0.0, now - t) / 3600
    items = {}
    for name, key, _unit in METRICS:
        if d is None or age_h is None or age_h > STALE_H:
            items[name] = missing("no digest in the last day")
            continue
        m = (d.get("metrics") or {}).get(key) or {}
        if not _number(m.get("value")) or m.get("modality") not in _WEAKEST_LAST:
            items[name] = missing(f"today's digest has no {key}")
            continue
        t1 = _t1(lab, key, m["value"], m["modality"])
        if t1["label"] == _labeler.UNKNOWN:
            items[name] = envelope(None, m["modality"], age_h, reason=f"today's {key} has no coarse label")
            continue
        items[name] = envelope(t1["label"], m["modality"], age_h)
        items[name]["label"] = t1
        if raw:
            items[name]["raw"] = m["value"]
    return items, age_h


def _metric_text(name: str, env: dict, unit: str) -> str:
    if env["value"] is None:
        return f"{name} unknown ({env['reason']})"
    raw = f", {env['raw']}{unit}" if "raw" in env else ""
    return f"{name} {env['value']} ({env['modality']}{raw})"


def _owner_text(owner: dict) -> str:
    """"; messages: <T1 label>" once owner session DBs are configured; nothing when they are not."""
    word = (owner.get("label") or {}).get("label")
    return f"; messages: {word}" if isinstance(word, str) and not any(c.isdigit() for c in word) else ""


def build(reader: StateReader, now: float, today: date, *, raw: bool = False,
          win: Optional[dict] = None, bands: Optional[Mapping] = None,
          labeler: Optional[Callable] = None, env: Optional[Mapping[str, str]] = None,
          owner: Optional[dict] = None) -> dict:
    """{"text", "lines", "items", "age_h"} for the card; at most MAX_LINES lines.
    labeler(kind, value, modality) -> T1 dict; the rule labeler by default. ``owner`` is a ready
    tools.owner_message envelope (read from ``env`` when not given)."""
    win = win or window(reader, now, bands)
    items, digest_age = _metric_items(reader, now, raw, labeler or _labeler.label)
    items["window"] = win
    owner = owner if owner is not None else tools.owner_message(reader, now, env)
    items["owner_message"] = owner
    lines = ["[limitless] state card (coarse labels; limitless_state has detail)",
             f"window: {win['value']}" + (f" ({win['modality']})" if win["value"] != "unknown" else "")
             + _owner_text(owner),
             "; ".join(_metric_text(n, items[n], u) for n, _, u in METRICS)]
    h = tools.habit(reader, now, today)
    items["habit_today"] = h if h["value"] is None else envelope(h["value"]["today"], "self_report", h["age_h"])
    if h["value"] is None:
        lines.append("habit: none set this week")
    else:
        lines.append(f"habit this week: {h['value']['habit']}; today {h['value']['today']}")
    st = tools.status(reader, now)
    if st["value"] and st["value"]["not_recording"]:
        lines.append("not recording: " + ", ".join(st["value"]["not_recording"]))
    asks = reader.asks() or {}
    asks_at = parse_ts(asks.get("at"))
    if asks_at is not None and now - asks_at <= ASKS_MAX_AGE_H * 3600 and asks.get("count"):
        lines.append("asks waiting on you" + (f": {asks['count']}" if raw else ""))
    lines = lines[:MAX_LINES]
    if not raw and MASK_DIGITS:
        lines = [re.sub(r"\d+", "#", ln) for ln in lines]
    return {"text": "\n".join(lines), "lines": lines, "items": items, "age_h": digest_age}


def state(reader: StateReader, now: float, today: date, *, raw: bool = False,
          bands: Optional[Mapping] = None, labeler: Optional[Callable] = None,
          env: Optional[Mapping[str, str]] = None) -> dict:
    """limitless_state: today's card plus its parts, each an envelope. Modality = the weakest part's."""
    if not reader.exists():
        return missing("the state dir does not exist")
    c = build(reader, now, today, raw=raw, bands=bands, labeler=labeler, env=env)
    mods = [e["modality"] for e in c["items"].values() if e["value"] is not None and e["modality"]]
    if not mods:
        return envelope(None, "proxy", c["age_h"], reason="no state for today: every part is unknown")
    weakest = max(mods, key=_WEAKEST_LAST.index)
    return envelope({"card": c["lines"], "items": c["items"]}, weakest, c["age_h"])


class CardCache:
    def __init__(self):
        self._key, self._text, self.builds = None, None, 0

    def get(self, reader: StateReader, now: float, today: date, raw: bool = False,
            bands: Optional[Mapping] = None, labeler: Optional[Callable] = None,
            env: Optional[Mapping[str, str]] = None) -> str:
        win = window(reader, now, bands)
        owner = tools.owner_message(reader, now, env)
        key = (str(reader.path), win["value"], today, raw, tuple(reader.mtime(n) for n in CARD_FILES),
               tuple(getattr(labeler, "cmd", None) or ()), _owner_text(owner))
        if key != self._key:
            self._text = build(reader, now, today, raw=raw, win=win, bands=bands, labeler=labeler,
                               owner=owner)["text"]
            self._key = key
            self.builds += 1
        return self._text


def raw_in_prompt(env: Mapping[str, str]) -> bool:
    return env.get("LIMITLESS_RAW_IN_PROMPT") == "1"


def make_pre_llm_call(env: Optional[Mapping[str, str]] = None, clock: Callable[[], float] = time.time,
                      today: Callable[[], date] = date.today, bands: Optional[Mapping] = None):
    cache = CardCache()

    def pre_llm_call(**kwargs) -> Optional[dict]:
        e = os.environ if env is None else env
        reader = StateReader(state_dir(e))
        if not reader.exists():
            return None
        now, raw = clock(), raw_in_prompt(e)
        text = cache.get(reader, now, today(), raw=raw, bands=bands, labeler=_labeler.from_config(e), env=e)
        text = tier_audit.gate("pre_llm_call", text, raw, env=e, now=now)  # a digit without the opt-in: drop
        return None if text is None else {"context": text}

    return pre_llm_call
