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
While the phase is just_woke (phase.read_for: the first short span after the wake event, config
phase_light_h; never a clock time) the card says "Light: outdoor light now helps set the day." on a line of its
own under the window and peak lines, or after the window line's words when the card is full; nothing in any
other phase. No new job, push or reminder: the line only rides on the card.
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
The same trough, with config ``palace_link`` set, no Anki offer on this card, not muted and once per wake event
(palace.for_turn), adds "A short memory palace walk fits now. <link>" on a line of its own after the card
(outside MAX_LINES, so the link stays whole); once the gate lets that card through, the hook marks the wake as
offered (palace.json). build() adds it only when given ``palace_offer``.
Sleep debt (tools.sleep_debt over the wearable sleep file and the phone proxy; sleep_debt.debt) adds its digit-free
words on a line of their own right under the sleep and readiness line: "some sleep debt", "a lot of sleep debt
(phone estimate)", ...; nothing when it is unknown (too few nights). Only a sleep_debt.KNOWN_LABELS word is used;
the card never shows the minutes, not even under the raw opt-in (limitless_sleep_debt has them).
When phone pushes cannot reach the person (push_reach: kevin-push's sender profile is missing, the profile the
owner's reply named was set but could not send (push_recovery.UNKNOWN_FAILED), or the last pushes failed to send
per the delivery audit of config ``push_log``) the card says so in words on a line of its
own, "Phone pushes are not reaching you: <reason>", after the MAX_LINES cap (so a full card never cuts it) and
before the palace and explain-back offers; nothing when the sender is set and the last push was delivered, or
when neither can be told. While the owner's reply is what moves the outage on (push_recovery.stage missing with
WAITING_REPLY, REFUSED or UNKNOWN_FAILED) the same line goes on with the reply that fixes it (push_reach.hint):
"Reply push via <name> to fix it." for the one ready profile, "Reply push via one of: a, b." for several, else
"Reply with a profile that has a Telegram bot." The hook caches it with the card: per turn only stats (the config
file, the profile directory, the Hermes home's profiles dir, the push log), and the log is read only when the
card is rebuilt. items["delivery"] carries the line without the hint.
While today's wake brief is missed (missed_brief.find: built and logged today, no delivered brief by the delivery
audit's rule, no older than the wake job's stale_after_s) the card says "Today's wake brief did not reach your
phone; ask me for it." on a line of its own right after the push-reach line, outside MAX_LINES like it; the
hook caches it with the card (the push log's stat, the wake event files' stats) and rebuilds once the offer goes
stale. limitless_missed_brief returns the brief itself.
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

from . import anki as _anki, bedtime, explain_back as _explain_back, flow_week, modes, peak as _peak, phase as _phase
from . import aw_desktop
from . import missed_brief as _missed_brief
from . import palace as _palace
from . import push_reach as _push_reach
from . import labeler as _labeler
from . import sleep_debt as _sleep_debt
from . import tier_audit, tools
from . import weekly_target as _weekly_target
from .decision_window import UNKNOWN
from .envelope import STALE_H, envelope, missing
from .glide_provider import GlideProvider
from .state_reader import StateReader, config as _read_config, config_path, parse_ts, state_dir
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
    before, in this machine's zone; None when neither the ActivityWatch DB nor the desktop's ActivityWatch
    (aw_desktop: desktop_aw_url or desktop_aw_export) is configured."""
    if reader.aw_db_path(env) is None and not aw_desktop.configured(env):
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


DESKTOP_REFRESH_S = 3600.0   # with a desktop source set, the card's flow label is rebuilt at most this often


def _desktop_tick(now: float, env: Optional[Mapping[str, str]]) -> Optional[int]:
    """A cache-key part for the desktop's ActivityWatch, which has no file mtime: the DESKTOP_REFRESH_S slot
    ``now`` falls in when it is configured, else None (no change to the key)."""
    return int(now // DESKTOP_REFRESH_S) if aw_desktop.configured(env) else None


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


def debt_line(reader: StateReader, now: float, today: date, env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """The sleep debt words (tools.sleep_debt, never its numbers) when known, else None; only a
    sleep_debt.KNOWN_LABELS word, and a digit drops it. Read-only; never raises."""
    try:
        if not reader.exists():
            return None
        word = ((tools.sleep_debt(reader, now, today, raw=False, env=env) or {}).get("value") or {}).get("label")
    except Exception:  # noqa: BLE001 - a broken input must not break the card
        return None
    ok = isinstance(word, str) and word in _sleep_debt.KNOWN_LABELS and not any(c.isdigit() for c in word)
    return word if ok else None


def light_line(reader: StateReader, now: float, env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """phase.CARD_LINE while the phase is just_woke (phase.read_for), else None; a digit drops it. Never raises."""
    try:
        if _phase.read_for(reader, now, env)["phase"] != "just_woke":
            return None
        word = _phase.CARD_LINE
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


def palace_offer(reader: StateReader, now: float, win: dict, env: Optional[Mapping[str, str]] = None,
                 anki_line: Optional[str] = None) -> dict:
    """palace.for_turn in the window anki_offer sees, with this turn's Anki offer: ``{line, wake, word, reason,
    words}``. Read-only; never raises (an error is no offer)."""
    try:
        return _palace.for_turn(reader, now, _trough_state(reader, now, win, env), anki_line or "", env)
    except Exception:  # noqa: BLE001 - a broken input must not break the card
        return {"line": None, "wake": None, "word": _palace.NOT_NOW, "reason": _palace.BROKEN,
                "words": f"{_palace.NOT_NOW}: {_palace.BROKEN}"}


def _config(env: Optional[Mapping[str, str]] = None) -> dict:
    """The host config (state_reader.config); read only when the card's push reach is worked out."""
    return _read_config(env)


def reach_reason(reader: StateReader, today: date, env: Optional[Mapping[str, str]] = None,
                 cfg: Optional[Mapping] = None) -> Optional[str]:
    """push_reach.reason for this card (config read when ``cfg`` is not given; local zone). Never raises."""
    try:
        return _push_reach.reason(_config(env) if cfg is None else cfg, reader.path, today, env)
    except Exception:  # noqa: BLE001 - a broken input must not break the card
        return None


def reach_hint(reader: StateReader, env: Optional[Mapping[str, str]] = None,
               cfg: Optional[Mapping] = None) -> Optional[str]:
    """push_reach.hint for this card (config read when ``cfg`` is not given). Never raises."""
    try:
        return _push_reach.hint(_config(env) if cfg is None else cfg, reader.path, env)
    except Exception:  # noqa: BLE001 - a broken input must not break the card
        return None


def missed(reader: StateReader, now: float, env: Optional[Mapping[str, str]] = None,
           cfg: Optional[Mapping] = None) -> dict:
    """missed_brief.find for this card (config read when ``cfg`` is not given; local zone). Never raises."""
    try:
        return _missed_brief.find(_config(env) if cfg is None else cfg, reader.path, now, env)
    except Exception:  # noqa: BLE001 - a broken input must not break the card
        return {"missed": False, "until": None}


def build(reader: StateReader, now: float, today: date, *, raw: bool = False,
          win: Optional[dict] = None, bands: Optional[Mapping] = None,
          labeler: Optional[Callable] = None, env: Optional[Mapping[str, str]] = None,
          owner: Optional[dict] = None, peak: Any = _UNSET, anki_offer: Optional[str] = None,
          explain_offer: Optional[str] = None, mask: bool = True, light: Any = _UNSET,
          palace_offer: Optional[str] = None, debt: Any = _UNSET, reach: Any = _UNSET,
          missed_brief: Any = _UNSET, hint: Any = _UNSET) -> dict:
    """{"text", "lines", "items", "age_h"} for the card; at most MAX_LINES lines.
    ``mask=False`` leaves a digit in place (never adds a raw value) so a caller that drops digit lines, as
    ui_card does through tier_audit.gate, sees it; the prompt card keeps the default.
    labeler(kind, value, modality) -> T1 dict; the rule labeler by default. ``owner`` is a ready
    tools.owner_message envelope (read from ``env`` when not given). ``reach`` is a push_reach reason (or None),
    worked out from ``env`` when not given; ``missed_brief`` is a missed_brief.find result, likewise; ``hint`` is
    a push_reach.hint (or None), worked out from ``env`` when not given and there is an outage line."""
    win = win or window(reader, now, bands)
    items, digest_age = _metric_items(reader, now, raw, labeler or _labeler.label)
    items["window"] = win
    owner = owner if owner is not None else tools.owner_message(reader, now, env)
    items["owner_message"] = owner
    lines = ["[limitless] state card (coarse labels; limitless_state has detail)",
             f"window: {win['value']}" + (f" ({win['modality']})" if win["value"] != "unknown" else "")
             + _owner_text(owner),
             "; ".join(_metric_text(n, items[n], u) for n, _, u in METRICS)]
    owed = debt_line(reader, now, today, env) if debt is _UNSET else debt
    if isinstance(owed, str) and owed in _sleep_debt.KNOWN_LABELS:
        lines.append(owed)   # its own line under the sleep line; the card has three lines here, so it fits
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
    at = 2
    if word:
        if len(lines) < MAX_LINES:
            lines.insert(2, word)
            at = 3
        else:
            lines[1] += f"; {word}"
    lit = light_line(reader, now, env) if light is _UNSET else light
    if lit:
        if len(lines) < MAX_LINES:
            lines.insert(at, lit)
        else:
            lines[1] += f"; {lit}"
    lines = lines[:MAX_LINES]
    why = reach_reason(reader, today, env) if reach is _UNSET else reach
    items["delivery"] = _push_reach.item(why)
    outage = _push_reach.line(why)
    if outage:
        outage = _push_reach.line(why, reach_hint(reader, env) if hint is _UNSET else hint)
    if outage:
        lines.append(outage)   # its own line, outside MAX_LINES: a full card never cuts it
    late = _missed_brief.line(missed(reader, now, env) if missed_brief is _UNSET else missed_brief)
    if late:
        lines.append(late)     # right after the push-reach line, outside MAX_LINES like it
    if palace_offer:
        lines.append(palace_offer)    # its own line, outside MAX_LINES: the link stays whole
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
        self.palace = None   # (line, wake) of the last get's memory palace offer, for the hook's mark
        self._cfg_key, self._cfg = _UNSET, None   # the config, re-read only when its file's stat changes
        self._until = None   # when the cached card's missed-brief line goes stale (None: no line)

    def _config_for(self, env: Optional[Mapping[str, str]]) -> dict:
        """The host config, cached under its path and mtime: a turn that changes nothing reads no file."""
        path = config_path(env)
        try:
            key = (str(path), path.stat().st_mtime_ns)
        except OSError:
            key = (str(path), None)
        if key != self._cfg_key:
            self._cfg, self._cfg_key = _config(env), key
        return self._cfg

    def get(self, reader: StateReader, now: float, today: date, raw: bool = False,
            bands: Optional[Mapping] = None, labeler: Optional[Callable] = None,
            env: Optional[Mapping[str, str]] = None) -> str:
        win = window(reader, now, bands)
        owner = tools.owner_message(reader, now, env)
        word = peak_label(reader, now, env)   # the peak closes with time, not a file change: part of the key
        offer = anki_offer(reader, now, win, env)   # Glide's block and the mode change it too: part of the key
        lit = light_line(reader, now, env)   # the light part ends with time since the wake: part of the key
        explain, self.wake = explain_offer(reader, now, win, env)   # the mark and landed work change it too
        pal = palace_offer(reader, now, win, env, offer)   # quiet and its mark change it too: part of the key
        owed = debt_line(reader, now, today, env)   # the sleep file and the phone's nights change it: part of the key
        self.palace = (pal["line"], pal["wake"]) if pal["line"] else None
        cfg = self._config_for(env)
        reach = _push_reach.key(cfg, reader.path, env)   # stats only: the profile dirs and the push log's mtime
        key = (str(reader.path), win["value"], today, raw, tuple(reader.mtime(n) for n in CARD_FILES),
               tuple(getattr(labeler, "cmd", None) or ()), _owner_text(owner), _aw_mtime(reader, env),
               _desktop_tick(now, env), _passive_mtime(reader, env), word, offer, lit, explain, pal["line"], owed,
               reach, _missed_brief.key(reader.path))   # stats only: the wake event files
        if key != self._key or (self._until is not None and now > self._until):
            late = missed(reader, now, env, cfg)
            why = reach_reason(reader, today, env, cfg)
            self._text = build(reader, now, today, raw=raw, win=win, bands=bands, labeler=labeler,
                               owner=owner, env=env, peak=word, anki_offer=offer, light=lit,
                               explain_offer=explain, palace_offer=pal["line"], debt=owed,
                               reach=why, missed_brief=late,
                               hint=reach_hint(reader, env, cfg) if why else None)["text"]
            self._until = late.get("until") if late.get("missed") else None
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
        if cache.palace is not None and cache.palace[1] is not None and cache.palace[0] in text.splitlines():
            _palace.mark(reader.path, cache.palace[1], now)   # the one palace offer for this wake event
        return {"context": text}

    return pre_llm_call
