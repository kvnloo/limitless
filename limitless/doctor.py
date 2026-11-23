"""limitless-doctor: a read-only report of which inputs are live and which tools would answer unknown, and why.

    report(cfg, now) -> [{"name", "kind", "status", "reason"}]

status is one of STATUSES: live, stale, missing or off. The rows are the state dir (exists, readable), each
input named in inputs.json against the stale threshold limitless_status already uses (envelope.STALE_H), the
last sync run's age in words from runs.jsonl, and one row per tool in plugin.yaml, from that tool's own
envelope for an empty call. Reasons are words only: a digit is never printed, and neither is a tool's value.
Nothing here writes, sends, pushes or starts a job.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from . import tools
from .state_reader import StateReader

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
        next(iter(os.scandir(path)), None)
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


def report(cfg: Mapping, now: float) -> list:
    """Every row, in order: state dir, inputs, the last sync run, then each plugin tool."""
    path = state_path(cfg)
    reader = StateReader(path)
    return [state_row(path)] + input_rows(tools.status(reader, now))
