"""The work-app and feed-app lists, set from one reply: ``work apps: A, B`` / ``feed apps: C, D``.

    got = parse(text)        # {"work_apps": (...), "feed_apps": (...)} for the lists named, or None

A whole message is read. Its first non-empty line must start with ``work apps:`` or ``feed apps:`` (any
case, loose spacing); names follow on that line and the next ones, comma or newline separated, trimmed and
de-duplicated (case-insensitively, the first spelling kept), until a line that starts the other list. Both
lists may be in one message. ``none`` alone clears a list. A list with no name, more than MAX_NAMES names or
a name longer than MAX_LEN characters, the same list twice, or any text before the first prefix makes the
whole message not a command: it changes nothing.

Replies (``ingest``, bin/limitless-apps-ingest [--db PATH] [--write], the quiet-ingest shape): the person's
Telegram messages from the Hermes session DB (read-only), after ``read_after`` (the second after the current
``since``; with no valid apps.json, FIRST_READ_S back, so a first run never acts on an old message). Per list
the newest command wins; ``apps.json`` in the state dir is ``{"since": ISO UTC, "work_apps": [...],
"feed_apps": [...]}``, written atomically with mode 0600, a list no reply named kept as it was. Dry run
unless written. Rows never echo a reply or a name. The config file is never edited. Nothing here sends.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional, Tuple

WORK, FEED = "work_apps", "feed_apps"
MAX_NAMES, MAX_LEN = 20, 60
CLEAR = "none"
_PREFIX = re.compile(r"^\s*(work|feed)\s+apps\s*:(.*)$", re.IGNORECASE | re.DOTALL)
_KEYS = {"work": WORK, "feed": FEED}


def clean(items: Iterable) -> tuple:
    """Trimmed, non-empty strings, de-duplicated case-insensitively in first-seen order."""
    out, seen = [], set()
    for v in items or ():
        w = v.strip() if isinstance(v, str) else ""
        if w and w.casefold() not in seen:
            seen.add(w.casefold())
            out.append(w)
    return tuple(out)


def _names(parts: list) -> Optional[tuple]:
    names = clean(p for chunk in parts for p in chunk.split(","))
    if not names:
        return None
    if len(names) == 1 and names[0].casefold() == CLEAR:
        return ()
    if len(names) > MAX_NAMES or any(len(n) > MAX_LEN for n in names):
        return None
    return names


def starts_reply(line) -> bool:
    """True when ``line`` starts a ``work apps:`` or ``feed apps:`` list (the prefix parse reads)."""
    return isinstance(line, str) and _PREFIX.match(line) is not None


def parse(text) -> Optional[dict]:
    """``{list key: names}`` for each list a whole message sets (``()`` clears), or None for anything else."""
    if not isinstance(text, str):
        return None
    lists, key = {}, None
    for line in text.splitlines():
        m = _PREFIX.match(line)
        if m:
            key = _KEYS[m.group(1).lower()]
            if key in lists:
                return None
            lists[key] = [m.group(2)]
        elif key is not None:
            lists[key].append(line)
        elif line.strip():
            return None
    if not lists:
        return None
    out = {}
    for k, parts in lists.items():
        names = _names(parts)
        if names is None:
            return None
        out[k] = names
    return out


# --- apps.json: the lists set from a reply ----------------------------------------------------------------

APPS_FILE = "apps.json"
WRITE, WOULD_WRITE, IGNORE, NOTHING = "write", "would write", "ignore", "nothing"
FIRST_READ_S = 24 * 3600   # ingest only: how far back a first run (no apps.json) reads replies
_WORDS = {WORK: "work apps", FEED: "feed apps"}


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def iso(t: float) -> str:
    """UTC ISO time in whole seconds (the fraction is cut)."""
    return datetime.fromtimestamp(int(float(t)), timezone.utc).isoformat(timespec="seconds")


def load(state_dir) -> Optional[dict]:
    """apps.json as a dict, or None when it is missing, unreadable or not an object."""
    try:
        data = json.loads((Path(state_dir) / APPS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _since(state) -> Optional[float]:
    v = state.get("since") if isinstance(state, dict) else None
    if not isinstance(v, str):
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.timestamp() if dt.tzinfo is not None else None


def stored(state, key: str) -> tuple:
    """One list from an apps.json dict, cleaned; () when absent or not a list."""
    v = state.get(key) if isinstance(state, dict) else None
    return clean(v) if isinstance(v, list) else ()


def write(state_dir, obj: dict) -> dict:
    """Write apps.json atomically (temp file in the state dir, mode 0600, then a rename)."""
    d = Path(state_dir)
    fd, tmp = tempfile.mkstemp(prefix=".apps-", suffix=".tmp", dir=str(d))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, d / APPS_FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return obj


def read_after(state_dir, now: float) -> float:
    """Epoch seconds after which replies are read: the second after the current ``since``, else FIRST_READ_S
    before ``now``."""
    since = _since(load(state_dir))
    return since + 1 if since is not None else float(now) - FIRST_READ_S


def _row(t, keys, action, reason) -> dict:
    return {"reply_at": None if t is None else iso(t), "lists": [_WORDS[k] for k in keys],
            "action": action, "reason": reason}


def ingest(state_dir, replies: Iterable[Tuple[float, str]], now: float, dry_run: bool = True) -> dict:
    """``{"rows", "apps"}``: one plain-word row per reply (or one ``nothing`` row), never a name or the reply;
    ``apps`` is the apps.json it writes (only when not ``dry_run``) or would write, None when nothing changes.
    Per list the newest reply after the current ``since`` wins; the other list is kept as it is."""
    start = read_after(state_dir, now)
    ok = sorted(((float(t), x) for t, x in (replies or ()) if _number(t)), key=lambda r: r[0])
    if not ok:
        return {"rows": [_row(None, (), NOTHING, "no new message: the app lists stay as they are")], "apps": None}
    rows, parsed, newest = [], [], {}
    for i, (t, text) in enumerate(ok):
        got = parse(text)
        parsed.append(got)
        if int(t) < start:
            rows.append(_row(t, (), IGNORE, "before the current app lists"))
        elif t > now:
            rows.append(_row(t, (), IGNORE, "after now"))
        elif got is None:
            rows.append(_row(t, (), IGNORE, "not work apps or feed apps: changes nothing"))
        else:
            rows.append(None)
            for k in got:
                newest[k] = i
    if not newest:
        return {"rows": rows, "apps": None}
    act = WOULD_WRITE if dry_run else WRITE
    for i, r in enumerate(rows):
        if r is None:
            keys = [k for k in (WORK, FEED) if newest.get(k) == i]
            rows[i] = (_row(ok[i][0], keys, act, "the newest reply for these lists") if keys
                       else _row(ok[i][0], (), IGNORE, "a later reply wins"))
    old = load(state_dir)
    apps = {"since": iso(ok[max(newest.values())][0])}
    for k in (WORK, FEED):
        apps[k] = list(parsed[newest[k]][k]) if k in newest else list(stored(old, k))
    if not dry_run:
        write(state_dir, apps)
    return {"rows": rows, "apps": apps}


# --- where each list comes from: env, then config, then apps.json --------------------------------------------

ENV, CONFIG, REPLY = "env", "config", "reply"
ENV_KEYS = {WORK: "LIMITLESS_FLOW_WORK_APPS", FEED: "LIMITLESS_FEED_APPS"}
CONFIG_KEYS = {WORK: "flow_work_apps", FEED: "feed_apps"}


def _listed(v) -> tuple:
    if isinstance(v, str):
        v = v.split(",")
    return clean(v) if isinstance(v, (list, tuple)) else ()


def list_for(key: str, cfg: Mapping, state_dir, env: Optional[Mapping[str, str]] = None) -> Tuple[tuple, Optional[str]]:
    """``(names, source)`` for WORK or FEED: env ENV_KEYS (a comma list), else config CONFIG_KEYS (a list or a
    comma string), else apps.json in ``state_dir`` (set from a reply); ``((), None)`` when none is set. A blank
    or empty value at one step falls through to the next, so a list set in config always beats a reply."""
    env = os.environ if env is None else env
    got = _listed(env.get(ENV_KEYS[key]))
    if got:
        return got, ENV
    got = _listed(cfg.get(CONFIG_KEYS[key]) if isinstance(cfg, Mapping) else None)
    if got:
        return got, CONFIG
    got = stored(load(state_dir), key) if state_dir is not None else ()
    return (got, REPLY) if got else ((), None)


def lists_for(cfg: Mapping, state_dir, env: Optional[Mapping[str, str]] = None) -> dict:
    """``{WORK: (names, source), FEED: (names, source)}`` (list_for for both lists)."""
    return {k: list_for(k, cfg, state_dir, env) for k in (WORK, FEED)}


def host_list(key: str, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> tuple:
    """list_for with the host config (state_reader.config) and state dir (state_reader.state_dir)."""
    from .state_reader import config, state_dir
    return list_for(key, config(env, home), state_dir(env, home), env)[0]


def lines(got: dict, written: bool) -> list:
    """The CLI's plain lines for an ingest() result: one per row, then what it wrote or would write (the
    one place a name is shown, to the person running it), then the dry-run note."""
    out = []
    for r in got["rows"]:
        lists = f"{', '.join(r['lists'])}: " if r["lists"] else ""
        out.append(f"{r['reply_at'] or 'no reply'}: {r['action']}: {lists}{r['reason']}")
    if got["apps"] is not None:
        out.append(f"{'wrote' if written else 'would write'} {APPS_FILE}: {json.dumps(got['apps'])}")
    if not written:
        out.append(f"dry run: nothing written (--write writes {APPS_FILE})")
    return out
