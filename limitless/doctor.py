"""limitless-doctor: a read-only report of which inputs are live and which tools would answer unknown, and why.

    report(cfg, now) -> [{"name", "kind", "status", "reason"}]

status is one of STATUSES: live, stale, missing or off. The rows are the state dir (exists, readable), each
input named in inputs.json against the stale threshold limitless_status already uses (envelope.STALE_H), the
last sync run's age in words from runs.jsonl, and one row per tool in plugin.yaml, from that tool's own
envelope for an empty call. Reasons are words only: a digit is never printed, and neither is a tool's value.
Nothing here writes, sends, pushes or starts a job.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Mapping, Optional

from . import card, tier_audit, tools
from .envelope import STALE_H
from .state_reader import StateReader, config, parse_ts

LIVE, STALE, MISSING, OFF = "live", "stale", "missing", "off"
STATUSES = (LIVE, STALE, MISSING, OFF)


def _row(name: str, kind: str, status: str, reason: str) -> dict:
    return {"name": name, "kind": kind, "status": status, "reason": reason}


def state_path(cfg: Mapping, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Path:
    """$LIMITLESS_STATE, else "state" in cfg, else ~/.local/state/limitless (state_reader.state_dir's rule)."""
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    if env.get("LIMITLESS_STATE"):
        return Path(env["LIMITLESS_STATE"])
    st = cfg.get("state") if isinstance(cfg, Mapping) else None
    return Path(st) if isinstance(st, str) and st else home / ".local/state/limitless"


def state_row(path: Path) -> dict:
    if not path.is_dir():
        return _row("state dir", "state", MISSING, "the state dir does not exist")
    try:
        with os.scandir(path) as it:
            next(it, None)
    except OSError:
        return _row("state dir", "state", MISSING, "the state dir exists but is not readable")
    return _row("state dir", "state", LIVE, "the state dir exists and is readable")


INPUT_WORDS = {   # limitless_status's state per input -> (status, reason)
    "recording": (LIVE, "recording: updated within the last day"),
    "not recording": (STALE, "not recording: no update for over a day"),
    "down": (STALE, "not recording: the sync reports it down"),
    "unknown": (MISSING, "no age for this input in inputs.json"),
}


def input_rows(status_env: dict) -> list:
    """One row per input named in inputs.json, from limitless_status (tools.status): the same STALE_H
    threshold, the same snapshot-age rule. No inputs file is one missing row with that tool's reason."""
    if not isinstance(status_env, dict) or status_env.get("value") is None:
        reason = (status_env or {}).get("reason") or "no inputs.json in the state dir"
        return [_row("inputs", "input", MISSING, reason)]
    out = []
    for name, got in sorted(status_env["value"]["inputs"].items()):
        status, reason = INPUT_WORDS.get(got.get("state"), INPUT_WORDS["unknown"])
        out.append(_row(f"input {name}", "input", status, reason))
    return out


_NUMBERS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
            "sixteen seventeen eighteen nineteen twenty twenty-one twenty-two twenty-three").split()


def age_words(age_h: float) -> str:
    """An age in hours as words, never a digit: under an hour, about N hours, about N days, over a week ago."""
    if age_h < 1:
        return "under an hour ago"
    if age_h < 2:
        return "about an hour ago"
    if age_h < 24:
        return f"about {_NUMBERS[int(age_h)]} hours ago"
    if age_h < 48:
        return "about a day ago"
    if age_h < 7 * 24:
        return f"about {_NUMBERS[int(age_h // 24)]} days ago"
    return "over a week ago"


def run_row(reader: StateReader, now: float) -> dict:
    """The last valid row of runs.jsonl (StateReader.last_run): live when at most STALE_H old and not failed."""
    run = reader.last_run()
    at = parse_ts((run or {}).get("at"))
    if at is None or not math.isfinite(at):
        return _row("last sync run", "run", MISSING, "no timestamped row in runs.jsonl")
    age_h = (now - at) / 3600
    if age_h < 0:
        return _row("last sync run", "run", STALE, "the last sync run is timestamped in the future")
    ok = run.get("ok")
    tail = " and failed" if ok is False else " and finished ok" if ok is True else ""
    status = LIVE if age_h <= STALE_H and ok is not False else STALE
    return _row("last sync run", "run", status, f"the last sync run was {age_words(age_h)}{tail}")


MANIFEST = Path(__file__).resolve().parents[1] / "plugin.yaml"


def manifest_tools(path: Path = MANIFEST) -> list:
    """The names under ``provides_tools:`` in plugin.yaml (stdlib only: the simple ``  - name`` lines)."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out, inside = [], False
    for ln in lines:
        if ln.strip() == "provides_tools:":
            inside = True
        elif inside and ln.startswith("  - "):
            out.append(ln[4:].strip())
        elif inside:
            break
    return out


def _card_view(args, now):
    """limitless_card_view's default call (kind state), rendered only: the doctor never writes a card file."""
    from . import card_view, labeler, plugin
    from .state_reader import state_dir
    return card_view.view(state_dir(), now, date.fromtimestamp(now), "state", bands=plugin._bands(),
                          labeler=labeler.from_config(), write=False)


# tools whose plugin function would write for an empty call: the doctor calls a read-only twin instead
READ_ONLY_CALLS = {"limitless_card_view": _card_view}

# a feature off by config still answers with a value: these read the value to say so
OFF_WHEN = {
    "limitless_focus_safe": (lambda e: (e.get("value") or {}).get("mode") == "off",
                             "the focus guard is off (config focus_safe)"),
    "limitless_breathing": (lambda e: (e.get("value") or {}).get("link_set") is False,
                            "no breathing link set (config wind_down_breathing_link)"),
    "limitless_palace": (lambda e: "why" in (e.get("value") or {}),
                         "no memory palace link set (config palace_link)"),
    "limitless_card_view": (lambda e: bool(e.get("note")),
                            "no card dir set (config card_dir): the card is rendered only"),
}
# a null value whose reason says an input or feature is not configured: "...: set X in config", "... set"
_NOT_SET = re.compile(r": set \S|\bset$|\bset \(")
_DIGITS = re.compile(r"\d+(?:[.,:]\d+)*")
TIER_WORDS = {
    "direct": "answers from direct evidence",
    "indirect": "answers from a proxy",
    "observed-activity": "answers from observed app activity",
    "none": "answers, with nothing measured behind it yet",
}


def words(text) -> str:
    """A reason as words only: every number becomes "a number"."""
    return _DIGITS.sub("a number", str(text)).strip()


def _unknown(value) -> bool:
    if value == "unknown":
        return True
    return isinstance(value, dict) and any(v == "unknown" for v in value.values())


def classify(name: str, env, needs_args: bool = False) -> tuple:
    """(status, reason) for one tool from its envelope. The value itself is read, never returned."""
    if not isinstance(env, dict):
        return MISSING, "the tool returned no envelope"
    value = env.get("value")
    if value is None or (_unknown(value) and env.get("reason")):
        reason = str(env.get("reason") or "no reason given")
        if needs_args:
            return MISSING, words(f"needs its arguments: {reason}")
        return (OFF if _NOT_SET.search(reason) else MISSING), words(reason)
    off = OFF_WHEN.get(name)
    if off is not None and off[0](env):
        return OFF, off[1]
    tier = env.get("evidence_tier")
    if tier == "stale":
        return STALE, "answers, but its evidence is stale or of unknown age"
    return LIVE, TIER_WORDS.get(tier, "answers")


def tool_row(name: str, now: float) -> dict:
    """Call the tool's plugin function with {} as its handler does (tools.labeled, then tier_audit.audit_result)
    at ``now``, with the audit log held (tier_audit.held: nothing appended), and read its envelope."""
    from . import plugin
    entry = plugin.TOOLS.get(name)
    if entry is None:
        return _row(f"tool {name}", "tool", MISSING, "listed in plugin.yaml but not registered")
    schema, fn = entry[0], READ_ONLY_CALLS.get(name, entry[1])
    needs_args = bool(((schema or {}).get("parameters") or {}).get("required"))
    try:
        with tier_audit.held():
            env = tier_audit.audit_result(f"tool:{name}", tools.labeled(fn({}, now)),
                                          card.raw_in_prompt(os.environ), now=now)
    except Exception as exc:  # noqa: BLE001 - a failing tool is a row, never a traceback (its message stays out)
        return _row(f"tool {name}", "tool", MISSING, f"the tool failed with {type(exc).__name__}")
    status, reason = classify(name, env, needs_args)
    return _row(f"tool {name}", "tool", status, reason)


def report(cfg: Mapping, now: float) -> list:
    """Every row, in order: state dir, inputs, the last sync run, then each tool in plugin.yaml.

    cfg is the host config (state_reader.config()); the tools read the same config through the environment,
    as they do inside Hermes."""
    path = state_path(cfg)
    reader = StateReader(path)
    rows = [state_row(path)] + input_rows(tools.status(reader, now)) + [run_row(reader, now)]
    rows += [tool_row(name, now) for name in manifest_tools()]
    return [dict(r, reason=words(r["reason"])) for r in rows]


def text(rows: list) -> str:
    """One line per row: ``name: status: reason``."""
    return "\n".join(f"{r['name']}: {r['status']}: {r['reason']}" for r in rows)


def as_json(rows: list) -> str:
    """The full rows as a JSON list, one row per line."""
    return "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n]"


def strict_failed(rows: list) -> bool:
    """--strict: true when the state dir, an input or the last sync run is not live (tool rows never count)."""
    return any(r["kind"] != "tool" and r["status"] != LIVE for r in rows)


def main(argv=None, now: Optional[float] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="limitless-doctor", description="Read-only: which inputs are live and which "
                                "tools would answer unknown, and why. Never writes, sends or starts a job.")
    p.add_argument("--json", action="store_true", help="print the full rows as JSON")
    p.add_argument("--strict", action="store_true",
                   help="exit 1 when the state dir, an input or the last sync run is not live")
    args = p.parse_args(argv)
    rows = report(config(), time.time() if now is None else now)
    print(as_json(rows) if args.json else text(rows))
    return 1 if args.strict and strict_failed(rows) else 0
