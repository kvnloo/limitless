"""The app-lists ask: one pre-filled ``work apps: / feed apps:`` reply in the wake brief while both lists are unset.

    lines = ask_lines(cfg, state_dir, now, env=None, home=None)   # [] or [PROMPT, reply text]
    tell(state_dir, now)                                           # marks it told (only after a delivery)
    word = state(cfg, state_dir, now, env=None)                    # OFF, NOT_NEEDED, TOLD_RECENTLY or WAITING

ask_lines is ``[]`` when config ``apps_ask`` is off, when either list is already set (apps_reply.lists_for: the
environment, then config, then apps.json from a reply), when the ask was told less than TOLD_FOR_S (seven days)
before ``now``, or when the candidates are unknown (app_candidates.read_for: no source, too little app time, no
well-known work or feed app). Else two lines: PROMPT, then the reply text exactly as app_candidates.reply_line
returns it, so the person can send it back (edited or not) and apps_reply reads it.

The seven days are a duration since the last delivered ask, never a time of day. The mark file ``apps-ask.json``
(atomic, 0600) holds one epoch only, ``{"told": t}``: never an app name. A missing or malformed mark is never told.
Nothing here marks it told on its own: the brief's sender calls tell only after a real delivery.

App names are the person's own data: they appear only in the lines returned here, which ride in the brief sent
to the person; never in the state card, a doctor reason, a log row, a T1 label or the mark. Nothing here sends,
pushes, writes config or starts anything. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Mapping, Optional

MARK_FILE = "apps-ask.json"
CONFIG_KEY = "apps_ask"
TOLD_FOR_S = 7 * 86400.0
PROMPT = "Reply with this to set your app lists (edit freely):"
OFF_WORDS = ("off", "false", "no")

OFF, NOT_NEEDED, TOLD_RECENTLY, WAITING = "off", "not needed", "told recently", "waiting"


def enabled(cfg: Mapping) -> bool:
    """Config ``apps_ask``: on unless false (or "off"/"false"/"no")."""
    v = cfg.get(CONFIG_KEY, True) if isinstance(cfg, Mapping) else True
    if v is False:
        return False
    return not (isinstance(v, str) and v.strip().lower() in OFF_WORDS)


def lists_set(cfg: Mapping, state_dir, env: Optional[Mapping[str, str]] = None) -> bool:
    """True when either list is set (apps_reply.lists_for: env, config or apps.json)."""
    from . import apps_reply
    return any(src for _, src in apps_reply.lists_for(cfg, state_dir, env).values())


def told_at(state_dir) -> Optional[float]:
    """The epoch of the last delivered ask from apps-ask.json; None when missing or malformed."""
    try:
        data = json.loads((Path(state_dir) / MARK_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    v = data.get("told") if isinstance(data, dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def told_recently(state_dir, now: float) -> bool:
    """True when the ask was delivered less than TOLD_FOR_S before ``now`` (a duration, not a time of day)."""
    t = told_at(state_dir)
    return t is not None and float(now) - t < TOLD_FOR_S


def tell(state_dir, now: float) -> bool:
    """Write ``{"told": now}`` to apps-ask.json, atomic and 0600. Call it only after the brief was delivered.
    True when written; never raises."""
    try:
        d = Path(state_dir)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".apps-ask.", suffix=".tmp")
        try:
            try:
                os.fchmod(fd, 0o600)
                os.write(fd, json.dumps({"told": float(now)}).encode("utf-8"))
            finally:
                os.close(fd)
            os.replace(tmp, d / MARK_FILE)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except Exception:  # noqa: BLE001 - a failed mark must not stop the brief
        return False


def state(cfg: Mapping, state_dir, now: float, env: Optional[Mapping[str, str]] = None) -> str:
    """Where the ask stands, in words: OFF, NOT_NEEDED (a list is set), TOLD_RECENTLY or WAITING (the next brief
    asks once the candidates are known). Reads config and the two small files only; never app time."""
    if not enabled(cfg):
        return OFF
    if lists_set(cfg, state_dir, env):
        return NOT_NEEDED
    return TOLD_RECENTLY if told_recently(state_dir, now) else WAITING


def ask_lines(cfg: Mapping, state_dir, now: float, env: Optional[Mapping[str, str]] = None,
              home: Optional[Path] = None) -> list:
    """``[PROMPT, reply]`` while both lists are unset and the ask was not told in the last seven days; ``[]``
    when off, a list is set, told recently or the candidates are unknown. Read-only."""
    if state(cfg, state_dir, now, env) != WAITING:
        return []
    from . import app_candidates
    from .state_reader import StateReader
    text = app_candidates.reply_line(app_candidates.read_for(StateReader(Path(state_dir)), now, env, home))
    return [PROMPT, text] if text else []
