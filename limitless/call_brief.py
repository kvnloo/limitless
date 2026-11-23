"""Call brief: today's digit-free state card as a small Markdown file a voice call opens with.

    render(reader, now, today) -> {"body", "lines"}
    text(body, now)            -> the file: one header comment, then the body
    write(out, reader, now, today) -> (exit code, one-line reason)   (bin/limitless-call-brief)

The body is a TLDR line first, then at most MAX_BODY short lines, all from the T2 state card (card.build with
raw=False: coarse labels, every digit masked), the window class (window.py) and the asks label
(tools.asks_view: "one decision ready", "decisions waiting", "nothing waiting"):

    <!-- limitless call brief; generated: 2030-01-15T12:00:00Z -->
    TLDR: peak window; asks waiting
    sleep short (proxy); readiness low (imported)
    habit this week: Lights down when wind-down starts; today Done
    not recording: anki, bike, scale

No numbers, no card ids (send_gate's ``t_...`` ids, also in their masked form), no message content: the
card's "messages:" recency label and its asks line are left out (the TLDR carries the asks). The body goes
through tier_audit.gate (hook "call_brief", never opted in): a digit refuses the write. The ``generated``
stamp (UTC) is outside the gated body so a reader can ignore a stale brief.

The reader in mind is z0live's voice-adapter/call_brief.py ``written()``: it reads ``<chat>.md`` or
``latest.md`` from its brief dir as plain text when the file's mtime is under three hours old. See
docs/call-brief.md. Nothing here sends. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

from . import asks as _asks
from . import card, tier_audit, tools
from . import labeler as _labeler
from .state_reader import StateReader, config, state_dir

HOOK = "call_brief"
CONFIG_KEY = "call_brief_file"
MAX_BODY = 3
LINE_MAX = 100
HEADER = "<!-- limitless call brief; generated: {} -->"
_HEADER_RE = re.compile(r"^<!-- limitless call brief; generated: [^>]*-->$")
_ID = re.compile(r"[ \t]*\bt_[0-9a-f#]{2,12}(?![\w#]):?")   # a card id, before or after digit masking
_WINDOW = {"peak": "peak window", "trough": "trough window", "anytime": "anytime window", "asleep": "asleep"}
_SKIP = ("[limitless]", "window:", "asks waiting")   # header, window (in the TLDR), asks (in the TLDR)


def _short(line: str) -> str:
    line = " ".join(_ID.sub("", line).split())
    if len(line) <= LINE_MAX:
        return line
    cut = line[:LINE_MAX - 3].rsplit(" ", 1)[0]
    return cut.rstrip(" ;,:") + "..."


def _asks_word(reader: StateReader, now: float, card_lines: list, env, bands) -> Optional[str]:
    """The asks queue's T1 label when a queue is configured, else "asks waiting" from the card, else None."""
    if _asks.queue_path(env) is not None:
        word = (tools.asks_view(reader, now, bands, env).get("label") or {}).get("label")
        if isinstance(word, str):
            return word
    return "asks waiting" if any(ln.startswith("asks waiting") for ln in card_lines) else None


def render(reader: StateReader, now: float, today: date, *, env: Optional[Mapping[str, str]] = None,
           bands: Optional[Mapping] = None) -> dict:
    """{"body", "lines"}: TLDR first, then at most MAX_BODY lines of at most LINE_MAX characters."""
    env = os.environ if env is None else env
    c = card.build(reader, now, today, raw=False, bands=bands, labeler=_labeler.from_config(env), env=env)
    win = c["items"]["window"]["value"]
    tldr = [_WINDOW.get(win, "window unknown")]
    asks = _asks_word(reader, now, c["lines"], env, bands)
    if asks:
        tldr.append(asks)
    rest = [ln for ln in c["lines"] if not ln.startswith(_SKIP)]
    lines = [_short("TLDR: " + "; ".join(tldr))] + [_short(ln) for ln in rest if _short(ln)][:MAX_BODY]
    return {"body": "\n".join(lines), "lines": lines}


def _iso(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def text(body: str, now: float) -> str:
    """The file: the ``generated`` header comment, then the body, newline-terminated."""
    return HEADER.format(_iso(now)) + "\n" + body.strip("\n") + "\n"


def _bands(env: Mapping[str, str]) -> Optional[dict]:
    b = config(env).get("window_bands")
    return b if isinstance(b, dict) else None


def write_atomic(out: Path, body: str) -> None:
    """Write ``body`` to ``out`` through a 0600 temp file in the same directory and a rename."""
    fd, tmp = tempfile.mkstemp(dir=str(out.parent), prefix="." + out.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, str(out))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _same(out: Path, body: str) -> bool:
    """True when ``out`` already holds our header and exactly ``body``: then it is not touched (mtime kept)."""
    try:
        old = out.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False
    head, _, rest = old.partition("\n")
    return bool(_HEADER_RE.match(head)) and rest == body.strip("\n") + "\n"


def out_path(flag, env: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    """--out when given, else config ``call_brief_file`` (a relative path is in the state dir); None when
    neither names a path."""
    env = os.environ if env is None else env
    if isinstance(flag, (str, Path)) and str(flag).strip():
        return Path(flag).expanduser()
    v = config(env).get(CONFIG_KEY)
    if not isinstance(v, str) or not v.strip():
        return None
    p = Path(v).expanduser()
    return p if p.is_absolute() else state_dir(env) / p


def write(out, now: float, today: date, *, env: Optional[Mapping[str, str]] = None) -> tuple:
    """(exit code, one-line reason) for writing the brief to ``out`` (None: config ``call_brief_file``).
    0 written, unchanged or nothing to do; 1 cannot build or write; 2 refused (a digit). Never raises."""
    env = os.environ if env is None else env
    try:
        return _write(out, now, today, env)
    except Exception as e:  # noqa: BLE001 - a broken state or config is one line, never a traceback
        return 1, f"could not write the call brief: {type(e).__name__}"


def _write(out, now: float, today: date, env: Mapping[str, str]) -> tuple:
    out = out_path(out, env)
    if out is None:
        return 0, "not configured"
    try:
        reader = StateReader(state_dir(env))
        if not reader.exists():
            return 0, "nothing written: the state dir does not exist"
        body = render(reader, now, today, env=env, bands=_bands(env))["body"]
    except Exception as e:  # noqa: BLE001
        return 1, f"could not build the call brief: {type(e).__name__}"
    if tier_audit.gate(HOOK, body, False, env=env, now=now) is None:
        return 2, "refused: the brief had a digit; nothing written"
    if _same(out, body):
        return 0, "call brief unchanged"
    try:
        write_atomic(out, text(body, now))
    except OSError as e:
        return 1, f"could not write the call brief: {e.strerror or type(e).__name__}"
    return 0, "call brief written"
