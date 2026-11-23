"""Today's state card: the limitless_state tool and the pre_llm_call hook.

Privacy tier T2 (default): the card carries coarse labels only ("sleep short (proxy)", "readiness low"),
made at the source by the T1 labeler (labeler.py: rules, or an optional local model), so its lines never
hold a raw value. Every digit left in it is masked as a second guard (MASK_DIGITS). LIMITLESS_RAW_IN_PROMPT=1
opts in to raw numbers. Labels describe one imported or proxy value; nothing here computes a score.
The hook's card is cached until the window class, a card input file's mtime, the date, the raw flag or the
owner-message label (tools.owner_message: one short read-only probe of each owner session DB per turn) changes.
A bedtime capture last night (bedtime.saved_last_night) adds the digit-free line "ideas saved last night".
While the post-wake peak applies (peak.read_for: from the wake event, never a clock time) the card says
"post-wake peak: open" or "post-wake peak: in use" on a line of its own under the window line, or after the
window line's words when the card is full; nothing when the peak is closed or unknown.
Once this week's Done days reach the weekly target (tools.habit ``target``) the habit line says
"target reached this week"; before that it says nothing about a target, and never a count.
The habit line gains the passive habit days' T1 words (tools.habit ``passive``, a proxy) when there are any,
e.g. "habit: none set this week; phone data shows the first hour mostly feed-free"; never a count.
In a trough window with an Anki collection set (anki.offer: the window chain, Glide first, would deliver a
trough job; never in a peak, asleep, an unknown window, a focus block or focused mode) the hook's card adds
"trough: a short Anki review fits now", on a line of its own or after the last line's words when the card is
full. Only the pre_llm_call card has it (CardCache); build() adds it only when given ``anki_offer``.
The same trough, once per wake event and only after work landed in the work queue (explain_back.for_turn),
adds the explain-back offer "Explain back: say what landed in one breath. Reply: Voice / Later" on a line of its
own after the card (outside MAX_LINES, so the Reply choices stay whole); once the gate lets that card through,
the hook marks the wake as offered (explain-back.json). build() adds it only when given ``explain_offer``.
An attention mode (modes.py, ``mode.json``) adds its one digit-free line last, outside the cache and the
MAX_LINES cap; no mode adds nothing.
Each injection goes through tier_audit.gate: one content-free audit line, and a card with a digit but no
opt-in is dropped, not sent.
"""
from __future__ import annotations

import os
import re
import time
from datetime import date, timedelta
from typing import Any, Callable, Mapping, Optional

from . import anki as _anki, bedtime, explain_back as _explain_back, flow_week, modes, peak as _peak
from . import labeler as _labeler
from . import tier_audit, tools
from . import weekly_target as _weekly_target
from .decision_window import UNKNOWN
from .envelope import STALE_H, envelope, missing
from .glide_provider import GlideProvider
from .state_reader import StateReader, parse_ts, state_dir
from .window import window
from .window_chain import first_known

MAX_LINES = 6
ASKS_MAX_AGE_H = 36.0
CARD_FILES = ("inputs.json", "digests.jsonl", "habit.json", "asks-latest.json", "captures.jsonl",
              "sleepmode.jsonl")
SAVED_LABEL = "ideas saved last night"  # digit-free: the count is in the wake brief
_WEAKEST_LAST = ("measured", "messages", "imported", "self_report", "proxy")
MASK_DIGITS = True  # the second guard: lines are built from T1 labels first
_UNSET = object()


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


def flow_label(reader: StateReader, today: date, env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """The flow T1 label (flow_week.t1_label: digit-free) for the seven days to ``today`` against the seven
    before, in this machine's zone; None when no ActivityWatch DB is configured."""
    if reader.aw_db_path(env) is None:
        return None
    this = flow_week.for_week(reader, today - timedelta(days=6), None, env)
    last = flow_week.for_week(reader, today - timedelta(days=13), None, env)
    return flow_week.t1_label(this, last)


def _passive_word(hv: Optional[dict]) -> Optional[str]:
    """The passive habit days' digit-free T1 words (tools.habit value ``passive``), else None."""
    word = (((hv or {}).get("passive") or {}).get("label") or {}).get("label")
    return word if isinstance(word, str) and not any(ch.isdigit() for ch in word) else None


def _target_word(hv: Optional[dict]) -> Optional[str]:
    """"target reached this week" once tools.habit ``target`` is reached in an open week, else None."""
    t = (hv or {}).get("target") or {}
    word = (t.get("label") or {}).get("label")
    return word if t.get("reached") is True and word == _weekly_target.REACHED else None


def _passive_mtime(reader: StateReader, env: Optional[Mapping[str, str]]) -> Optional[int]:
    p = reader.passive_habit_file(env)
    try:
        return None if p is None else p.stat().st_mtime_ns
    except OSError:
        return None


def _aw_mtime(reader: StateReader, env: Optional[Mapping[str, str]]) -> Optional[int]:
    p = reader.aw_db_path(env)
    try:
        return None if p is None else p.stat().st_mtime_ns
    except OSError:
        return None


def _saved_last_night(reader: StateReader, now: float, env: Optional[Mapping[str, str]]) -> int:
    try:
        return bedtime.saved_last_night(reader.path, now, env=env)
    except Exception:  # noqa: BLE001 - a broken capture file must not break the card
        return 0


def peak_label(reader: StateReader, now: float, env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """The post-wake peak's digit-free words while it applies (peak.read_for), else None. Never raises."""
    try:
        word = _peak.read_for(reader, now, env).get("label")
    except Exception:  # noqa: BLE001 - a broken input must not break the card
        return None
    return word if isinstance(word, str) and not any(c.isdigit() for c in word) else None


def anki_offer(reader: StateReader, now: float, win: dict, env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """anki.offer for this turn: the window chain (Glide first, then ``win``), focused mode applied, and
    whether a collection is set (configured and the file is there; the DB is not opened). None when there is
    no offer. Never raises."""
    try:
        path = _anki.collection_path(env)
        return _anki.offer(_trough_state(reader, now, win, env), {"set": path is not None and path.is_file()}) or None
    except Exception:  # noqa: BLE001 - a broken input must not break the card
        return None


def _trough_state(reader: StateReader, now: float, win: dict, env: Optional[Mapping[str, str]] = None):
    """The window a trough offer sees: the window chain (Glide first, then ``win``), focused mode applied."""
    state = first_known(GlideProvider.from_config(env, now=now))
    if state.cls == UNKNOWN:
        state = win
    return modes.apply(state, modes.load(reader.path))


def explain_offer(reader: StateReader, now: float, win: dict, env: Optional[Mapping[str, str]] = None) -> tuple:
    """explain_back.for_turn in the window anki_offer sees: ``(line or None, wake)``. Never raises."""
    try:
        line, wake = _explain_back.for_turn(reader, now, _trough_state(reader, now, win, env), env)
        return line or None, wake
    except Exception:  # noqa: BLE001 - a broken input must not break the card
        return None, None


def build(reader: StateReader, now: float, today: date, *, raw: bool = False,
          win: Optional[dict] = None, bands: Optional[Mapping] = None,
          labeler: Optional[Callable] = None, env: Optional[Mapping[str, str]] = None,
          owner: Optional[dict] = None, peak: Any = _UNSET, anki_offer: Optional[str] = None,
          explain_offer: Optional[str] = None, mask: bool = True) -> dict:
    """{"text", "lines", "items", "age_h"} for the card; at most MAX_LINES lines.
    ``mask=False`` leaves a digit in place (never adds a raw value) so a caller that drops digit lines, as
    ui_card does through tier_audit.gate, sees it; the prompt card keeps the default.
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
    h = tools.habit(reader, now, today, env)
    hv = h["value"] if isinstance(h.get("value"), dict) else None
    if hv is not None and hv.get("habit"):
        items["habit_today"] = envelope(hv["today"], "self_report", h["age_h"])
        lines.append(f"habit this week: {hv['habit']}; today {hv['today']}")
        target = _target_word(hv)
        if target:
            lines[-1] += f"; {target}"
    else:
        items["habit_today"] = h if hv is None else missing(hv.get("reason") or "no habit set this week")
        lines.append("habit: none set this week")
    passive = _passive_word(hv)
    if passive:
        lines[-1] += f"; {passive}"
    flow = flow_label(reader, today, env)
    if flow is not None:
        lines[-1] += f"; flow: {flow}"
    st = tools.status(reader, now)
    if st["value"] and st["value"]["not_recording"]:
        lines.append("not recording: " + ", ".join(st["value"]["not_recording"]))
    asks = reader.asks() or {}
    asks_at = parse_ts(asks.get("at"))
    if asks_at is not None and now - asks_at <= ASKS_MAX_AGE_H * 3600 and asks.get("count"):
        lines.append("asks waiting on you" + (f": {asks['count']}" if raw else ""))
    if _saved_last_night(reader, now, env):
        if len(lines) < MAX_LINES:
            lines.append(SAVED_LABEL)
        else:
            lines[-1] += f"; {SAVED_LABEL}"
    if anki_offer:
        if len(lines) < MAX_LINES:
            lines.append(anki_offer)
        else:
            lines[-1] += f"; {anki_offer}"
    word = peak_label(reader, now, env) if peak is _UNSET else peak
    if word:
        if len(lines) < MAX_LINES:
            lines.insert(2, word)
        else:
            lines[1] += f"; {word}"
    lines = lines[:MAX_LINES]
    if explain_offer:
        lines.append(explain_offer)   # its own last line, outside MAX_LINES: the Reply choices stay whole
    if not raw and MASK_DIGITS and mask:
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
        self.wake = None   # the wake event of the last get's explain-back offer, for the hook's mark

    def get(self, reader: StateReader, now: float, today: date, raw: bool = False,
            bands: Optional[Mapping] = None, labeler: Optional[Callable] = None,
            env: Optional[Mapping[str, str]] = None) -> str:
        win = window(reader, now, bands)
        owner = tools.owner_message(reader, now, env)
        word = peak_label(reader, now, env)   # the peak closes with time, not a file change: part of the key
        offer = anki_offer(reader, now, win, env)   # Glide's block and the mode change it too: part of the key
        explain, self.wake = explain_offer(reader, now, win, env)   # the mark and landed work change it too
        key = (str(reader.path), win["value"], today, raw, tuple(reader.mtime(n) for n in CARD_FILES),
               tuple(getattr(labeler, "cmd", None) or ()), _owner_text(owner), _aw_mtime(reader, env),
               _passive_mtime(reader, env), word, offer, explain)
        if key != self._key:
            self._text = build(reader, now, today, raw=raw, win=win, bands=bands, labeler=labeler,
                               owner=owner, env=env, peak=word, anki_offer=offer, explain_offer=explain)["text"]
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
        mode_line = modes.line(modes.load(reader.path))   # attention mode: presentation only; none adds nothing
        if mode_line:
            text = f"{text}\n{mode_line}"
        text = tier_audit.gate("pre_llm_call", text, raw, env=e, now=now)  # a digit without the opt-in: drop
        if text is None:
            return None
        if cache.wake is not None and _explain_back.OFFER in text.splitlines():
            _explain_back.mark(reader.path, cache.wake, now)   # offered once for this wake event
        return {"context": text}

    return pre_llm_call
