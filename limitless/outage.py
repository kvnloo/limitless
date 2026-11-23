"""Input outages: an input that stops recording is said once, in plain words, with what would help.

    down(state_dir, now, cfg)      -> [{"name", "age_h"}]   inputs not live now (read-only)
    poll(state_dir, now, cfg)      -> [{"name", "since"}]   outages not yet told; records each start
    line(new, cfg, now)            -> "Not recording: wearable (since about two days ago). <hint>" or ""
    tell(state_dir, names, now)    marks those outages told (call it only once the brief went out)
    current(state_dir, now, cfg)   -> [{"name", "since"}]   every current outage (read-only)

"Live" is limitless_status's rule, read through the doctor (tools.status, doctor.input_rows): each input's
age in inputs.json plus the snapshot's age against envelope.STALE_H, or the sync reporting it down. An input
is down when that row says stale; one with no age at all is unknown, never an outage. An outage starts at the
first poll that sees the input not live (or, with an age, when it last recorded) and ends when it is live
again. Recovery clears its mark silently: there is no "back" message.

The mark file ``outage.json`` (atomic, 0600) holds input names and epoch seconds only:
``{"since": {name: t}, "told": {name: t}}``. Config: ``input_outage`` (default on; false or "off": no line
and no mark write), ``outage_ignore`` (input names never reported), ``outage_hints`` (input name -> one short
plain sentence; a hint with a digit is dropped). The line is digit-free (doctor.age_words, doctor.words).

Nothing here restarts, kills or starts anything, pushes or sends: the line rides in the wake brief.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Iterable, Mapping, Optional

from . import doctor, tools
from .state_reader import StateReader

MARK_FILE = "outage.json"
MODALITY = "derived"
NONE_DOWN = "every input is recording"
OFF_WORDS = ("off", "false", "no")
_SPLIT = re.compile(r"[_\-\s]+")
_DIGIT_EDGE = re.compile(r"(?<=\D)(?=\d)|(?<=\d)(?=\D)")


def enabled(cfg: Mapping) -> bool:
    """Config ``input_outage``: on unless false (or "off"/"false"/"no")."""
    v = cfg.get("input_outage", True) if isinstance(cfg, Mapping) else True
    if v is False:
        return False
    return not (isinstance(v, str) and v.strip().lower() in OFF_WORDS)


def ignored(cfg: Mapping) -> set:
    v = cfg.get("outage_ignore") if isinstance(cfg, Mapping) else None
    return {x for x in v if isinstance(x, str)} if isinstance(v, (list, tuple)) else set()


def hints(cfg: Mapping) -> dict:
    """``outage_hints`` as {name: sentence}, each stripped and ending in a full stop; digits drop the hint."""
    v = cfg.get("outage_hints") if isinstance(cfg, Mapping) else None
    out = {}
    for name, h in (v.items() if isinstance(v, Mapping) else ()):
        if isinstance(name, str) and isinstance(h, str) and h.strip() and not any(c.isdigit() for c in h):
            h = h.strip()
            out[name] = h if h[-1] in ".!?" else h + "."
    return out


def down(state_dir, now: float, cfg: Mapping) -> list:
    """Inputs not live at ``now`` (doctor's stale rows), minus ``outage_ignore``, sorted by name. Read-only."""
    env = tools.status(StateReader(Path(state_dir)), now)
    if not isinstance(env, dict) or env.get("value") is None:
        return []
    got = env["value"]["inputs"]
    skip = ignored(cfg)
    out = []
    for row in doctor.input_rows(env):
        name = row["name"][len("input "):]
        if row["status"] == doctor.STALE and name in got and name not in skip:
            out.append({"name": name, "age_h": got[name].get("age_h")})
    return out


# --- the mark file: input names and epoch seconds only ----------------------------------------------------

def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _times(part) -> Optional[dict]:
    if not isinstance(part, dict):
        return None
    out = {}
    for k, v in part.items():
        t = _num(v)
        if not isinstance(k, str) or t is None:
            return None
        out[k] = t
    return out


def load_mark(state_dir) -> dict:
    """``{"since": {name: t}, "told": {name: t}}`` from outage.json; empty when missing or malformed."""
    empty = {"since": {}, "told": {}}
    try:
        data = json.loads((Path(state_dir) / MARK_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict):
        return empty
    since, told = _times(data.get("since", {})), _times(data.get("told", {}))
    return empty if since is None or told is None else {"since": since, "told": told}


def _write(state_dir, mark: dict) -> bool:
    """outage.json, atomic and 0600. True when written; never raises."""
    try:
        d = Path(state_dir)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".outage.", suffix=".tmp")
        try:
            os.write(fd, json.dumps({"since": mark["since"], "told": mark["told"]}, sort_keys=True).encode("utf-8"))
        finally:
            os.close(fd)
        os.chmod(tmp, 0o600)
        os.replace(tmp, d / MARK_FILE)
        return True
    except Exception:  # noqa: BLE001 - a failed mark must not stop the brief
        return False


def _since(o: dict, mark: dict, now: float) -> float:
    """When the outage started: the last recording (an age), else the first poll that saw it (the mark)."""
    if isinstance(o.get("age_h"), (int, float)):
        return float(now - o["age_h"] * 3600)
    return mark["since"].get(o["name"], float(now))


def current(state_dir, now: float, cfg: Mapping) -> list:
    """Every current outage, ``[{"name", "since"}]``, told or not. Read-only."""
    if not enabled(cfg):
        return []
    mark = load_mark(state_dir)
    return [{"name": o["name"], "since": _since(o, mark, now)} for o in down(state_dir, now, cfg)]


def poll(state_dir, now: float, cfg: Mapping) -> list:
    """One poll: record each outage's start, drop recovered inputs (silently) and return the outages not yet
    told. Off: [] and nothing written."""
    if not enabled(cfg):
        return []
    mark = load_mark(state_dir)
    cur = down(state_dir, now, cfg)
    names = [o["name"] for o in cur]
    new_mark = {"since": {n: mark["since"].get(n, float(now)) for n in names},
                "told": {n: mark["told"][n] for n in names if n in mark["told"]}}
    if new_mark != mark or not (Path(state_dir) / MARK_FILE).exists() and names:
        _write(state_dir, new_mark)
    return [{"name": o["name"], "since": _since(o, new_mark, now)} for o in cur if o["name"] not in new_mark["told"]]


def tell(state_dir, names: Iterable[str], now: float) -> bool:
    """Mark these current outages told, so they are not said again until they end. Never raises."""
    mark = load_mark(state_dir)
    told = dict(mark["told"])
    for n in names:
        if n in mark["since"]:
            told[n] = float(now)
    return _write(state_dir, {"since": mark["since"], "told": told}) if told != mark["told"] else True


# --- words ------------------------------------------------------------------------------------------------

def name_words(name: str) -> str:
    """An input name as words: separators become spaces, a number becomes "a number"."""
    return doctor.words(" ".join(_SPLIT.split(_DIGIT_EDGE.sub(" ", name))).strip())


def _and(parts: list) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def since_words(since: float, now: float) -> str:
    """"since about two days ago" (doctor.age_words); under an hour is "since just now"."""
    words = doctor.age_words(max(0.0, now - since) / 3600)
    return "since just now" if words == doctor.age_words(0) else f"since {words}"


def _what(outs: list, now: float) -> str:
    """Names and since for the oldest of them: the brief's one phrase."""
    return f"{_and([name_words(o['name']) for o in outs])} ({since_words(min(o['since'] for o in outs), now)})"


def _each(outs: list, now: float) -> str:
    """Names grouped by their own since: "wearable (since about three days ago) and phone (since just now)"."""
    groups = {}
    for o in sorted(outs, key=lambda o: (o["since"], o["name"])):
        groups.setdefault(since_words(o["since"], now), []).append(name_words(o["name"]))
    return _and([f"{_and(names)} ({w})" for w, names in groups.items()])


def line(new: list, cfg: Mapping, now: float) -> str:
    """One line for the outages in ``new``: "Not recording: <names> (since about <age>). <hints>"; "" for none."""
    if not new or not enabled(cfg):
        return ""
    hs = hints(cfg)
    tips = []
    for o in new:
        h = hs.get(o["name"])
        if h and h not in tips:
            tips.append(h)
    return doctor.words(" ".join([f"Not recording: {_what(new, now)}."] + tips))


def label(outs: list, now: float) -> str:
    """The tool's phrase: "not recording: <names> (since about <age>)", grouped by each input's own since when they
    differ, or "every input is recording"."""
    return doctor.words(f"not recording: {_each(outs, now)}") if outs else NONE_DOWN


# --- limitless_outages: read-only ---------------------------------------------------------------------------

OFF_WHY = "the input outage notice is off"


def tool(state_dir, now: float, cfg: Mapping) -> dict:
    """limitless_outages: every current outage (told or not), in words. ``value: {label, inputs}`` with the label
    "not recording: <names> (since about <age>)" or "every input is recording" and ``inputs`` the names in
    words; off (config ``input_outage``) is ``{label: "off", why}``. No inputs.json is no value, with
    limitless_status's reason. Modality derived (from limitless_status), age_h None, evidence_tier that of the
    inputs snapshot (direct when fresh, stale when old). Digit-free. Nothing is written, marked or sent."""
    def result(value, tier):
        return {"value": value, "modality": MODALITY, "age_h": None, "evidence_tier": tier,
                "label": {"label": value["label"], "tier": "T1", "modality": MODALITY}}
    if not enabled(cfg):
        return result({"label": "off", "why": OFF_WHY}, "direct")
    env = tools.status(StateReader(Path(state_dir)), now)
    if not isinstance(env, dict) or env.get("value") is None:
        return env
    outs = current(state_dir, now, cfg)
    return result({"label": label(outs, now), "inputs": [name_words(o["name"]) for o in outs]},
                  env.get("evidence_tier") or "stale")
