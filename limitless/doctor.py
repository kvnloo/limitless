"""limitless-doctor: a read-only report of which inputs are live and which tools would answer unknown, and why.

    report(cfg, now) -> [{"name", "kind", "status", "reason"}]

status is one of STATUSES: live, stale, missing or off. The rows are the state dir (exists, readable), each
input named in inputs.json against the stale threshold limitless_status already uses (envelope.STALE_H), the
last sync run's age in words from runs.jsonl, one row per tool in plugin.yaml, from that tool's own
envelope for an empty call, the Open Wearables export's row (config open_wearables_export, its mark
open-wearables.json; the server is never called), the NOOP export job's row (config noop_export,
its mark noop-export.json) and, before both, the context packet's row (config context_packet_path: off, live
when written within STALE_H, else stale; read from the packet's own generated_at), with the voice MIQ's row
(config voice_miq, its mark voice-miq.json) just before it. Right after the tool rows comes the NOOP MCP row
(config noop_mcp and t0_tools; the server is never started), then the desktop ActivityWatch's row (config
desktop_aw_url or desktop_aw_export: off, live, stale, or unreachable as status missing; the only row that may
call a server, read-only, with a short timeout).
Reasons are words only: a digit is never printed, and neither is a tool's value.
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

from . import card, mock_guard, noop_mcp, tier_audit, tools
from .envelope import STALE_H
from .state_reader import StateReader, config, parse_ts

LIVE, STALE, MISSING, OFF = "live", "stale", "missing", "off"
STATUSES = (LIVE, STALE, MISSING, OFF)
STRICT_KINDS = ("state", "input", "run")   # the rows --strict counts


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
    "demo": (MISSING, "a demo or sample device: demo rows never count as live"),
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


NOOP_ROW = "job NOOP export"
_NOOP_MODE_WORDS = {"dry_run": "dry run mode (counts only, no file written)", "write": "write mode"}


def noop_export_row(reader: StateReader, cfg: Mapping, now: float) -> dict:
    """The NOOP export job (jobs.NOOP_EXPORT, config ``noop_export``) from runs.jsonl and its mark noop-export.json:
    off by config; stale while the newest sync copied the NOOP database and the export has not run after it, when
    no sync has copied it yet, or when the last run exported nothing or could not write; else live. Words only."""
    from . import jobs, jobs_runner   # jobs_runner -> noop_export; card imports jobs_runner too
    mode = jobs.noop_mode(cfg)
    if mode == jobs.NOOP_OFF:
        return _row(NOOP_ROW, "job", OFF, f"the NOOP export job is {jobs.NOOP_IS_OFF}")
    mark = jobs_runner.load_noop_mark(reader.path)
    v = jobs.noop_export_verdict(mode, reader.last_run(), mark.get("row_at"), now)
    if v.action == jobs.RUN:
        return _row(NOOP_ROW, "job", STALE, "a sync copied the NOOP database and the export has not run after it "
                                            "yet (limitless-jobs --send runs it)")
    if mark.get("ran_at") is None:
        return _row(NOOP_ROW, "job", STALE, f"on ({_NOOP_MODE_WORDS[mode]}), but no sync run has copied the NOOP "
                                            "database yet")
    ago = age_words(max(0.0, now - mark["ran_at"]) / 3600)
    said = mark["said"][0] if mark.get("said") else "nothing said"
    outcome = mark.get("outcome") or "unknown"
    ran = f"{_NOOP_MODE_WORDS.get(mark.get('mode'), 'unknown mode')}: ran {ago} after a sync that copied the NOOP " \
          f"database"
    if outcome == jobs_runner.NOOP_DONE:
        demo = f"; {mock_guard.LEFT_OUT}" if any(mock_guard.LEFT_OUT in s for s in mark.get("said") or ()) else ""
        return _row(NOOP_ROW, "job", LIVE, f"{ran}: {outcome}{demo}")
    if outcome == jobs_runner.NOOP_NOTHING:
        return _row(NOOP_ROW, "job", STALE, f"{ran}: {outcome}: {said}")
    return _row(NOOP_ROW, "job", STALE, f"{ran}: {outcome}")


NOOP_MCP_ROW = "NOOP MCP"
NOOP_MCP_WORDS = {   # noop_mcp.state -> (status, reason); never the command, an env value or the server name
    noop_mcp.OFF: (OFF, "no noop_mcp set"),
    noop_mcp.MALFORMED: (MISSING, "noop_mcp is set but is not a command list"),
    noop_mcp.REFUSED: (MISSING, "refused: t0_tools does not cover its tools"),
    noop_mcp.BY_HAND: (MISSING, "set but the host cannot register MCP servers; add it to mcp_servers by hand"),
}


def noop_mcp_row(cfg: Mapping) -> dict:
    """The NOOP agent MCP server (config ``noop_mcp``, noop_mcp.state): off when unset; refused while t0_tools
    does not cover its tools; else set, for the person to add to the host's mcp_servers (Hermes has no plugin API
    to register one). Reads config only: the server is never started and the host's config is never read."""
    status, reason = NOOP_MCP_WORDS[noop_mcp.state(cfg)]
    return _row(NOOP_MCP_ROW, "mcp", status, reason)


VOICE_MIQ_ROW = "job voice MIQ"
_VOICE_MODE_WORDS = {"dry_run": "dry run mode (nothing written)", "write": "write mode"}


def voice_miq_row(reader: StateReader, cfg: Mapping, now: float) -> dict:
    """The voice MIQ (voice_miq.run, config ``voice_miq``) from config and its mark voice-miq.json: off by config;
    missing without the call sessions dir (config ``voice_miq_sessions``); else live, with the mode and when the
    last spoken MIQ answer was captured. Never reads a call. Words only."""
    from . import voice_miq   # voice_miq -> jobs_runner -> card
    mode = voice_miq.mode(cfg)
    if mode == voice_miq.OFF:
        return _row(VOICE_MIQ_ROW, "job", OFF, f"the voice MIQ is off (config {voice_miq.CONFIG_KEY})")
    sessions = voice_miq.sessions_dir(cfg)
    if sessions is None:
        return _row(VOICE_MIQ_ROW, "job", MISSING, f"on, but the call sessions dir is not configured (config "
                                                   f"{voice_miq.SESSIONS_KEY})")
    if not sessions.is_dir():
        return _row(VOICE_MIQ_ROW, "job", MISSING, "on, but the call sessions dir does not exist")
    at = voice_miq.load_mark(reader.path).get("captured_at")
    said = "no spoken MIQ answer captured yet" if at is None else \
        f"last spoken MIQ answer captured {age_words(max(0.0, now - at) / 3600)}"
    return _row(VOICE_MIQ_ROW, "job", LIVE, f"{_VOICE_MODE_WORDS[mode]}: {said}")


PACKET_ROW = "export context packet"


def context_packet_row(cfg: Mapping, now: float) -> dict:
    """The context packet (limitless-context-packet --write, config ``context_packet_path``): off when unset; stale
    when not written yet, not a packet this plugin wrote, or older than STALE_H by its own generated_at; else live.
    Reads that one file; words only, never a path."""
    from . import context_packet as cp   # context_packet imports doctor (age_words)
    path = cp.resolve_path(cfg.get(cp.CONFIG_KEY) if isinstance(cfg, Mapping) else None, state_path(cfg))
    if path is None:
        return _row(PACKET_ROW, "export", OFF, f"the context packet is not written (config {cp.CONFIG_KEY})")
    if not path.is_file():
        return _row(PACKET_ROW, "export", STALE, "set, but not written yet (limitless-context-packet --write "
                                                 "writes it)")
    try:
        p = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        p = None
    at = parse_ts(p.get("generated_at")) if isinstance(p, dict) and p.get("schema") == cp.SCHEMA else None
    if at is None:
        return _row(PACKET_ROW, "export", STALE, "the file there is not a context packet this plugin wrote")
    age_h = max(0.0, now - at) / 3600
    if age_h > STALE_H:
        return _row(PACKET_ROW, "export", STALE, f"written {age_words(age_h)}: older than a day")
    return _row(PACKET_ROW, "export", LIVE, f"written {age_words(age_h)}")


OW_ROW = "export Open Wearables"
_OW_MODE_WORDS = {"dry_run": "dry run mode (counts only, no file written)", "write": "write mode"}


def open_wearables_row(reader: StateReader, cfg: Mapping, now: float) -> dict:
    """The Open Wearables export (config ``open_wearables_export``) from its mark open-wearables.json, never the
    server: off by config; live when the last run read the server within STALE_H; failing (stale) when it could
    not, with its one plain reason; stale when it has not run yet or its last good run is older. Words only."""
    from . import open_wearables as ow
    mode = ow.mode(cfg)
    if mode == ow.OFF:
        return _row(OW_ROW, "export", OFF, ow.IS_OFF)
    mark = ow.load_mark(reader.path)
    if mark.get("ran_at") is None:
        return _row(OW_ROW, "export", STALE, f"on ({_OW_MODE_WORDS[mode]}), but limitless-ow-export has not run "
                                             "yet")
    age_h = max(0.0, now - mark["ran_at"]) / 3600
    ran = f"{_OW_MODE_WORDS.get(mark.get('mode'), 'unknown mode')}: ran {age_words(age_h)}"
    said = mark.get("said") or "nothing said"
    if mark.get("outcome") != ow.DONE:
        return _row(OW_ROW, "export", STALE, f"failing: {ran}: {said}")
    return _row(OW_ROW, "export", LIVE if age_h <= STALE_H else STALE, f"{ran}: {said}")


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
    "limitless_outages": (lambda e: (e.get("value") or {}).get("label") == "off",
                          "the input outage notice is off (config input_outage)"),
    "limitless_result_tier": (lambda e: (e.get("value") or {}).get("tool_globs") == "no globs",
                              "no health tools listed (config t0_tools)"),
    "limitless_card_view": (lambda e: bool(e.get("note")),
                            "no card dir set (config card_dir): the card is rendered only"),
}
# a null value whose reason says an input or feature is not configured: "...: set X in config", "... set"
_NOT_SET = re.compile(r": set \S|\bset$|\bset \(")
_DIGITS = re.compile(r"\d+(?:[.,:]\d+)*")
# config keys a reason names whose digit is part of the name, not a value: kept as they are by words()
CONFIG_KEYS_WITH_A_DIGIT = ("t0_tools",)
_KEYS = re.compile("(" + "|".join(re.escape(k) for k in CONFIG_KEYS_WITH_A_DIGIT) + ")")
TIER_WORDS = {
    "direct": "answers from direct evidence",
    "indirect": "answers from a proxy",
    "observed-activity": "answers from observed app activity",
    "none": "answers, with nothing measured behind it yet",
}


def words(text) -> str:
    """A reason as words only: every number becomes "a number"; a key in CONFIG_KEYS_WITH_A_DIGIT stays."""
    return "".join(p if p in CONFIG_KEYS_WITH_A_DIGIT else _DIGITS.sub("a number", p)
                   for p in _KEYS.split(str(text))).strip()


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


DESKTOP_AW_ROW = "desktop AW"


def desktop_aw_row(cfg: Mapping, now: float, fetch=None) -> dict:
    """The desktop's ActivityWatch (aw_desktop: config ``desktop_aw_url``, else ``desktop_aw_export``), read for
    the STALE_H up to ``now``: off when unset (nothing is called); live when it shows app activity in that time;
    stale when it answers with none; unreachable (status missing) when it cannot be read, with the reason.
    Words only: never the address, a path, an app name or a title. Kind ``source``: --strict does not count it."""
    from . import aw_desktop
    got = aw_desktop.from_settings(cfg, state_path(cfg), now - STALE_H * 3600, now, fetch=fetch)
    if got["state"] == aw_desktop.OFF:
        return _row(DESKTOP_AW_ROW, "source", OFF, aw_desktop.OFF_WHY)
    if got["events"] is None:
        return _row(DESKTOP_AW_ROW, "source", MISSING, f"unreachable: {got['why']}")
    if got["newest"] is None:
        return _row(DESKTOP_AW_ROW, "source", STALE, "it answers, with no active app time in the last day")
    return _row(DESKTOP_AW_ROW, "source", LIVE,
                f"active app time {age_words(max(0.0, now - got['newest']) / 3600)}")


def report(cfg: Mapping, now: float) -> list:
    """Every row, in order: state dir, inputs, the last sync run, each tool in plugin.yaml, the context packet
    (context_packet_row), the Open Wearables export (open_wearables_row), the NOOP export job
    (noop_export_row). The NOOP MCP server's row (noop_mcp_row) comes right after the tools, then the
    desktop's ActivityWatch (desktop_aw_row), then the voice MIQ's row (voice_miq_row) just before the
    context packet's.

    cfg is the host config (state_reader.config()); the tools read the same config through the environment,
    as they do inside Hermes."""
    path = state_path(cfg)
    reader = StateReader(path)
    rows = [state_row(path)] + input_rows(tools.status(reader, now, cfg)) + [run_row(reader, now)]
    rows += [tool_row(name, now) for name in manifest_tools()]
    rows += [noop_mcp_row(cfg)]
    rows += [desktop_aw_row(cfg, now), voice_miq_row(reader, cfg, now)]
    rows += [context_packet_row(cfg, now), open_wearables_row(reader, cfg, now), noop_export_row(reader, cfg, now)]
    return [dict(r, reason=words(r["reason"])) for r in rows]


def text(rows: list) -> str:
    """One line per row: ``name: status: reason``."""
    return "\n".join(f"{r['name']}: {r['status']}: {r['reason']}" for r in rows)


def as_json(rows: list) -> str:
    """The full rows as a JSON list, one row per line."""
    return "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n]"


def strict_failed(rows: list) -> bool:
    """--strict: true when the state dir, an input or the last sync run is not live (tool and job rows never
    count)."""
    return any(r["kind"] in STRICT_KINDS and r["status"] != LIVE for r in rows)


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
