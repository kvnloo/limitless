"""Result tier: raw readings from a health tool never enter the prompt (privacy tier T0).

    transform(tool_name, result, status=None, cfg=None) -> str | None
    scrub(text) -> (text, count)

The plugin's own tools already return digit-free T1 labels, but a health MCP server or another health tool
returns raw readings straight into the model's context. Hermes runs every ``transform_tool_result`` callback
after a tool returns and before its result enters context; the first ``str`` returned replaces the result,
None leaves it alone, and the call is fail-open (hermes-agent ``model_tools.py``,
``_apply_transform_tool_result_hook``).

Config ``t0_tools`` is a list of fnmatch globs over tool names (case-sensitive; one string is a list of one;
default empty: the filter does nothing). An MCP tool is named ``mcp__<server>__<tool>`` with every character
outside ``[A-Za-z0-9_]`` turned into ``_`` (hermes-agent ``tools/mcp_tool_schema.py``,
``mcp_prefixed_tool_name``), so ``mcp__<server>__*`` covers one server. For a matching tool, every number in
the result becomes the words ``a number`` (PLACEHOLDER): readings with or without a unit (``61 bpm``,
``47.5ms``, ``-0.3``, ``88%``), timestamps, dates and clock times as one number each, ids that are numbers and
hex ids that start with a digit. A unit glued to a number stays as its own word (``a number ms``). Words and
field names stay, even with a digit inside (``spo2``, ``hr_7d``): a digit right after a letter, an underscore
or a dot is part of a word, not a reading. A result that is JSON stays valid JSON with the same keys in the
same order: each number becomes the placeholder string and each string value is scrubbed as text; true, false
and null stay.

None (the result is left alone) for: a tool no glob matches, config ``raw_numbers_opt_in`` true (only the JSON
true), an error result (``status`` error, or a JSON object with an ``error``), a result that is not a string,
or a result with no number. Nothing here raises: any exception is None, the same fail-open the host applies.

The hook (make_transform_tool_result, registered for Hermes ``transform_tool_result``) reads host config on
each call and, for each result it replaces, records one content-free tier_audit row (``result_event``: hook
``transform_tool_result:result_tier``, the glob that matched and the count of numbers replaced; never a
value, the text or a hash; nothing when the audit is off). A failed audit write never stops the replacement.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import re
import time
from fnmatch import fnmatchcase
from typing import Callable, Mapping, Optional, Tuple

from . import tier_audit
from .state_reader import config

T0_KEY, OPT_IN_KEY = "t0_tools", "raw_numbers_opt_in"
PLACEHOLDER = "a number"

_START = r"(?<![A-Za-z0-9_.])"
_TOKENS = "|".join((
    # an ISO timestamp or date, with its time and zone when present
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?)?(?:Z|[+-]\d{2}:?\d{2})?",
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",   # a uuid
    r"\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?",                                          # a clock time
    r"\d[0-9A-Za-z]*[A-Za-z][0-9A-Za-z]*\d[0-9A-Za-z]*",                             # a hex-like id
    r"[-+]?(?:\d+(?:[.,]\d+)*|\.\d+)(?:[eE][-+]?\d+)?",                               # a number
))
_NUMBER = re.compile(rf"{_START}(?:{_TOKENS})(?![0-9])")


def _sub(m) -> str:
    end = m.string[m.end():m.end() + 1]
    return PLACEHOLDER + (" " if end.isalpha() else "")


def scrub_text(text: str) -> Tuple[str, int]:
    """``text`` with every number as the placeholder, and how many were replaced."""
    return _NUMBER.subn(_sub, text)


def _walk(v) -> Tuple[object, int]:
    if isinstance(v, bool) or v is None:
        return v, 0
    if isinstance(v, (int, float)):
        return PLACEHOLDER, 1
    if isinstance(v, str):
        return scrub_text(v)
    if isinstance(v, list):
        out, n = [], 0
        for x in v:
            y, k = _walk(x)
            out.append(y)
            n += k
        return out, n
    if isinstance(v, dict):
        obj, n = {}, 0
        for key, x in v.items():   # keys stay exactly as they are
            obj[key], k = _walk(x)
            n += k
        return obj, n
    return v, 0


def scrub(result: str) -> Tuple[str, int]:
    """The result with every number replaced, and the count: JSON stays JSON (same keys), else plain text."""
    try:
        parsed = json.loads(result)
    except ValueError:
        return scrub_text(result)
    obj, n = _walk(parsed)
    return json.dumps(obj, ensure_ascii=False), n


def settings(cfg) -> Tuple[tuple, bool]:
    """``(globs, opt_in)`` from host config: the non-empty string globs of t0_tools, and the opt-in (JSON true
    only)."""
    if not isinstance(cfg, Mapping):
        return (), False
    raw = cfg.get(T0_KEY)
    items = [raw] if isinstance(raw, str) else raw if isinstance(raw, (list, tuple)) else []
    return tuple(g.strip() for g in items if isinstance(g, str) and g.strip()), cfg.get(OPT_IN_KEY) is True


def matching_glob(tool_name, globs) -> Optional[str]:
    """The first glob ``tool_name`` matches (case-sensitive), else None."""
    if not isinstance(tool_name, str):
        return None
    return next((g for g in globs if fnmatchcase(tool_name, g)), None)


def _is_error(result: str, status) -> bool:
    if status == "error":
        return True
    try:
        parsed = json.loads(result)
    except ValueError:
        return False
    return isinstance(parsed, dict) and bool(parsed.get("error"))


def apply(tool_name, result, status=None, cfg=None) -> Optional[Tuple[str, str, int]]:
    """``(replacement, glob, count)`` for a result to replace, else None. Never raises."""
    try:
        globs, opt_in = settings(cfg)
        if not globs or opt_in or not isinstance(result, str):
            return None
        glob = matching_glob(tool_name, globs)
        if glob is None or _is_error(result, status):
            return None
        text, n = scrub(result)
        return (text, glob, n) if n else None
    except Exception:  # noqa: BLE001 - fail open, as the host does
        return None


def transform(tool_name, result, status=None, cfg=None) -> Optional[str]:
    """The replacement result string, or None to leave the result alone. Never raises."""
    got = apply(tool_name, result, status, cfg)
    return got[0] if got else None


def make_transform_tool_result(clock: Callable[[], float] = time.time) -> Callable:
    """The Hermes ``transform_tool_result`` callback: the replacement string or None; never raises."""
    def transform_tool_result(tool_name: str = "", args=None, result=None, status=None, **kwargs) -> Optional[str]:
        try:
            got = apply(tool_name, result, status, config())
        except Exception:  # noqa: BLE001 - fail open: the result goes on unchanged
            return None
        if got is None:
            return None
        text, glob, n = got
        try:
            tier_audit.record(tier_audit.result_event(glob, n, clock()))
        except Exception:  # noqa: BLE001 - the audit must never put a raw result back in
            pass
        return text
    return transform_tool_result
