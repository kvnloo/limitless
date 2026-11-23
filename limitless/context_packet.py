"""The state card as one data-free context packet, so another long-horizon agent knows the person's state
without raw data.

    packet(state_dir, now, today) -> dict          # pure: reads what the card reads, writes nothing
    packet_path(env)                               # config "context_packet_path"; None (write nothing) by default
    write(p, path)                                 # atomic (temp file, fsync, rename), mode 0600

The shape (schema ``limitless.context/1``)::

    {"schema": "limitless.context/1", "generated_at": "<ISO UTC>",
     "rows": [{"key", "words", "modality", "evidence_tier", "age_words"}, ...],
     "window": "<words>", "asks": "<words>"}

It wraps card.build, the builder the pre_llm_call hook uses, and keeps only its T1 parts: one row per card item
(``items``: sleep, readiness, window, owner_message, habit_today, in that order), ``window`` from the window
item and ``asks`` from whether the card holds its "asks waiting on you" line. Nothing here reads a state file
itself, and a row takes only whitelisted fields of the item's envelope: never ``value`` when it holds a digit
(the owner item's value is a time; only its T1 label goes in), never ``raw``, never ``age_h`` (the age is in
words). The raw opt-in (LIMITLESS_RAW_IN_PROMPT) is ignored: the card is always built with raw off. No string
in the packet holds a digit except ``schema`` and ``generated_at``; a string that would is replaced by plain
words. No score, no count, no clock-time rule. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Mapping, Optional

from . import card, doctor, labeler as _labeler
from .state_reader import StateReader, config, state_dir

SCHEMA = "limitless.context/1"
CONFIG_KEY = "context_packet_path"
ASKS_WAITING = "asks waiting on you"
NO_ASKS = "no asks on the card"
UNKNOWN = "unknown"
NO_WORDS = "known, but held back: no digit-free words for it"
AGE_UNKNOWN = "age unknown"
ROW_FIELDS = ("key", "words", "modality", "evidence_tier", "age_words")


def _clean(s) -> bool:
    return isinstance(s, str) and bool(s.strip()) and not any(c.isdigit() for c in s)


def _words(env: Mapping) -> str:
    """The item in words: its T1 label, else its value when that is digit-free text, else why it is unknown."""
    lab = env.get("label")
    word = lab.get("label") if isinstance(lab, Mapping) else None
    value = env.get("value")
    if value is not None and _clean(word):
        return word
    if _clean(value):
        return value
    if value is None:
        reason = env.get("reason")
        return f"{UNKNOWN}: {reason}" if _clean(reason) else UNKNOWN
    return NO_WORDS


def _word_or_none(v) -> Optional[str]:
    return v if _clean(v) else None


def _age_words(age_h) -> str:
    if isinstance(age_h, bool) or not isinstance(age_h, (int, float)) or age_h < 0:
        return AGE_UNKNOWN
    return doctor.age_words(float(age_h))


def row(key: str, env: Mapping) -> dict:
    """One packet row from one card item's envelope; whitelisted fields only, every string digit-free."""
    return {"key": key if _clean(key) else UNKNOWN, "words": _words(env),
            "modality": _word_or_none(env.get("modality")),
            "evidence_tier": _word_or_none(env.get("evidence_tier")) or "none",
            "age_words": _age_words(env.get("age_h"))}


def generated_at(now: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))


def packet(state_dir, now: float, today: date, env: Optional[Mapping[str, str]] = None) -> dict:
    """The context packet for ``now``/``today`` from card.build's T1 parts (raw always off). Writes nothing."""
    e = os.environ if env is None else env
    c = card.build(StateReader(Path(state_dir)), now, today, raw=False, labeler=_labeler.from_config(e), env=e)
    items = c["items"]
    win = items.get("window") or {}
    return {"schema": SCHEMA, "generated_at": generated_at(now),
            "rows": [row(k, v) for k, v in items.items() if isinstance(v, Mapping)],
            "window": _word_or_none(win.get("value")) or UNKNOWN,
            "asks": ASKS_WAITING if ASKS_WAITING in c["lines"] else NO_ASKS}


def packet_path(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[Path]:
    """Config ``context_packet_path`` (a relative path is in the state dir); None when unset: write nothing."""
    env = os.environ if env is None else env
    return resolve_path(config(env, home).get(CONFIG_KEY), state_dir(env, home))


def resolve_path(v, state: Path) -> Optional[Path]:
    """A configured ``context_packet_path`` value as a path (relative: in ``state``); None when unset or blank."""
    if not isinstance(v, str) or not v.strip():
        return None
    p = Path(v).expanduser()
    return p if p.is_absolute() else Path(state) / p


def write(p: Mapping, path) -> str:
    """Write packet ``p`` as JSON to ``path`` atomically (temp file beside it, mode 0600, fsync, rename); the path
    as a string. A failed write leaves the old file as it was and no temp file, and raises."""
    target = Path(path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".context-packet-", suffix=".tmp", dir=str(target.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(p, ensure_ascii=False, indent=2) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return str(target)


def publish(state_dir_, now: float, today: date, env: Optional[Mapping[str, str]] = None,
            home: Optional[Path] = None) -> tuple:
    """(packet, path or None): the packet, written to packet_path() only when that is set."""
    p = packet(state_dir_, now, today, env)
    path = packet_path(env, home)
    return p, (None if path is None else write(p, path))


def text(p: Mapping) -> str:
    """The packet in words, one line per row, then the window and the asks; no generated_at, so no digit."""
    lines = [f"{r['key']}: {r['words']} ({r['modality'] or 'no modality'}, {r['evidence_tier']}, {r['age_words']})"
             for r in p["rows"]]
    return "\n".join(lines + [f"window: {p['window']}", f"asks: {p['asks']}"])


USAGE = "usage: limitless-context-packet [--write] [--json]"
NO_PATH = (f"no context packet path: set \"{CONFIG_KEY}\" in config.json to write the packet; nothing written")
DRY_RUN = "dry run: nothing written (run with --write to write the packet to config \"context_packet_path\")"


def main(argv, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None, now: Optional[float] = None,
         today: Optional[date] = None, out=None, err=None) -> int:
    """The CLI: prints the packet (words, or the JSON with --json; status lines then go to stderr) and writes it
    only with --write and a configured path. 0 when done or nothing to write, 1 when the write failed, 2 for bad
    arguments. Never prints a path or a traceback."""
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    env = os.environ if env is None else env
    args = list(argv)
    if len(set(args)) != len(args) or any(a not in ("--write", "--json") for a in args):
        print(USAGE, file=err)
        return 2
    as_json, do_write = "--json" in args, "--write" in args
    now = time.time() if now is None else now
    today = date.today() if today is None else today
    p = packet(state_dir(env, home), now, today, env)
    print(json.dumps(p, ensure_ascii=False, indent=2) if as_json else text(p), file=out)
    status = err if as_json else out
    if not do_write:
        print(DRY_RUN, file=status)
        return 0
    path = packet_path(env, home)
    if path is None:
        print(NO_PATH, file=status)
        return 0
    try:
        write(p, path)
    except OSError as e:
        print(f"not written: {e.strerror or type(e).__name__}", file=err)
        return 1
    print("written: the context packet (config \"context_packet_path\")", file=status)
    return 0
