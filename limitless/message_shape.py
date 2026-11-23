"""Message shape: every push is short, the most important line first (L17, F18: attention is a currency).

    shape(title, body, limits)  -> the body held to the limits
    fit(title, body, limits)    -> (text, folded, cut): the same text, with how many lines were folded and cut
    limits(cfg)                 -> {"max_lines", "max_line_chars"} from config, defaults for bad values

The first non-blank line is the TLDR: kept as it is, in first place. The closing ``Reply: A / B / C`` line
(one_tap.choices_line, the last line before any why-now line) and the ``Why now: ...`` line
(send_gate.outgoing) are always kept in their places; the Reply line is never cut, so a tap still parses.
When the message has more than ``max_lines`` non-blank lines, the middle lines past the limit are folded into
one plain line, "and four more lines in the plugin", the count said in words. Any other line longer than
``max_line_chars`` is cut at a word boundary and ends with an ellipsis, except a line that offers a link
(``scheme://...``, e.g. the wind-down breathing link): a cut link is a broken one, so it is kept whole. Nothing is reworded and nothing is
asked that was not asked; no digit is ever added. A message that already fits comes back byte for byte.

Used in one place: bin/kevin-push, on the text it hands to the transport (after send_gate.outgoing added the
why-now line), so every job and every older sender gets it. When anything was folded or cut it writes one
tier_audit.shape_event row (the two counts only). The dedupe key stays the message as it was sent to kevin-push.

Defaults: max_lines 6, max_line_chars 160; config ``message_max_lines`` (a whole number, at least
MIN_LINES) and ``message_max_line_chars`` (a whole number, at least MIN_LINE_CHARS); anything else is the
default. ``title`` is the push's subject: it is never changed and never counted. Pure: no clock, no file, no
send. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import re
from typing import Mapping, Optional, Tuple

from . import one_tap
from .send_gate import WHY_PREFIX
from .tier_audit import SHAPE_HOOK as AUDIT_HOOK  # noqa: F401 - the hook of the one row kevin-push writes

DEFAULT_MAX_LINES, DEFAULT_MAX_LINE_CHARS = 6, 160
MIN_LINES = 4            # the TLDR, the folded line, the Reply line and the Why-now line
MIN_LINE_CHARS = 40
CONFIG_LINES, CONFIG_CHARS = "message_max_lines", "message_max_line_chars"
ELLIPSIS = "…"
FOLD = "and {} more lines in the plugin"
_LINK = re.compile(r"[A-Za-z][A-Za-z+.-]*://\S")   # a line that offers a link is never cut: a cut link is broken
_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
          "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty")


def _whole(v, floor: int, default: int) -> int:
    ok = isinstance(v, int) and not isinstance(v, bool) and v >= floor
    return v if ok else default


def limits(cfg: Optional[Mapping] = None) -> dict:
    """The limits config names, with the default for any missing or bad value."""
    cfg = cfg if isinstance(cfg, Mapping) else {}
    return {"max_lines": _whole(cfg.get(CONFIG_LINES), MIN_LINES, DEFAULT_MAX_LINES),
            "max_line_chars": _whole(cfg.get(CONFIG_CHARS), MIN_LINE_CHARS, DEFAULT_MAX_LINE_CHARS)}


def count_words(n: int) -> str:
    """``n`` in words: "two" ... "twenty", then "many". Never a digit."""
    return _WORDS[n] if 0 <= n < len(_WORDS) else "many"


def fold_line(n: int) -> str:
    return FOLD.format(count_words(n))


def cut(line: str, max_chars: int) -> str:
    """``line`` when it fits, else its head up to the last whole word plus an ellipsis, at most ``max_chars``."""
    if len(line) <= max_chars or _LINK.search(line):
        return line
    room = max(max_chars - len(ELLIPSIS), 1)
    head = line[:room]
    if not line[room].isspace() and " " in head.strip():
        head = head[:head.rstrip().rfind(" ")]
    head = head.rstrip(" ,;:-")
    return (head or line[:room]) + ELLIPSIS


def _is_why(line: str) -> bool:
    return line.strip().startswith(WHY_PREFIX)


def fit(title: str, body: str, lim: Optional[Mapping] = None) -> Tuple[str, int, int]:
    """(text, folded, cut): ``body`` held to ``lim`` (limits(); None = defaults), the number of middle lines
    folded into the one fold line, and the number of lines cut short."""
    lim = limits({CONFIG_LINES: (lim or {}).get("max_lines"), CONFIG_CHARS: (lim or {}).get("max_line_chars")})
    if not isinstance(body, str) or not body.strip():
        return body, 0, 0
    rows = [ln for ln in body.splitlines() if ln.strip()]
    head, rest = rows[0], rows[1:]
    why = [rest.pop()] if rest and _is_why(rest[-1]) else []
    reply = [rest.pop()] if rest and one_tap.choices_of(rest[-1].strip()) is not None else []
    budget = lim["max_lines"] - 1 - len(reply) - len(why)
    folded = 0
    if len(rest) > budget:
        keep = max(budget - 1, 0)
        folded = len(rest) - keep
        rest = rest[:keep]
    middle = [cut(ln, lim["max_line_chars"]) for ln in rest]
    tail = [cut(ln, lim["max_line_chars"]) for ln in why]
    n_cut = sum(a != b for a, b in zip(rest + why, middle + tail))
    if not folded and not n_cut:
        return body, 0, 0
    out = [head] + middle + ([fold_line(folded)] if folded else []) + reply + tail
    return "\n".join(out), folded, n_cut


def shape(title: str, body: str, lim: Optional[Mapping] = None) -> str:
    """``body`` held to ``lim`` (see the module doc): the TLDR first, the Reply and Why-now lines kept."""
    return fit(title, body, lim)[0]
