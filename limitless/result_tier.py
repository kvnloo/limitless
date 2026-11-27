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

register(ctx) adds the hook unless a loaded host lacks the name: the published ctx API has no list of hook
names, so it reads ``VALID_HOOKS`` from the host's already-loaded ``hermes_cli.plugins`` module
(sys.modules only, never an import). A loaded host without the name, or with a table it cannot read (an older
Hermes), gets nothing and one content-free log line. With no host module loaded at all (a test ctx, or the
isolated capability probe of ``hermes plugins validate``) it registers: the plugin's requires_hermes floor
already guarantees the hook wherever Hermes loads it. The plugin's tools and other hooks load either way.

The tool (``tool``, limitless_result_tier) is read-only: ``value {filter (on or off), tool_globs (no globs, one
glob, two globs ... ten globs, many globs), raw_numbers_opt_in (on or off), host_hook (known, or unknown: this
host has no transform_tool_result hook)}``, modality derived, age_h None and a digit-free T1 label (result
filter off: no health tools listed; result filter off: raw numbers opted in; result filter on: two tool globs,
with ``, but this host has no result hook`` when the host lacks the hook). It never names a glob or a tool.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from fnmatch import fnmatchcase
from typing import Callable, Mapping, Optional, Tuple

from . import tier_audit
from .state_reader import config

T0_KEY, OPT_IN_KEY = "t0_tools", "raw_numbers_opt_in"
PLACEHOLDER = "a number"
HOOK_NAME = "transform_tool_result"
HOST_MODULE = "hermes_cli.plugins"
NO_HOST = "limitless: host has no transform_tool_result hook; the result tier filter is not registered"
HOST_FAILED = "limitless: the host refused the transform_tool_result hook; the result tier filter is not registered"
logger = logging.getLogger(__name__)

_START = r"(?<![A-Za-z0-9_.])"
_TOKENS = "|".join((
    # an ISO timestamp or date, with its time and zone when present
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?)?(?:Z|[+-]\d{2}:?\d{2})?",
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",   # a uuid
    r"\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?",                                          # a clock time
    r"\d+[A-Za-z]+\d[0-9A-Za-z]*",   # a hex-like id: digits, letters, a digit, ... (linear: no nested stars)
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


def host_knows(hook_name: str) -> bool:
    """True when the host's loaded plugins module lists ``hook_name`` in VALID_HOOKS; never imports."""
    hooks = getattr(sys.modules.get(HOST_MODULE), "VALID_HOOKS", None)
    return isinstance(hooks, (set, frozenset, list, tuple, dict)) and hook_name in hooks


def host_lacks(hook_name: str) -> bool:
    """True only when a host plugins module IS loaded and does not list ``hook_name``; never imports.

    No loaded host module (a bare test ctx, or ``hermes plugins validate``'s isolated capability probe, which
    deliberately imports nothing from Hermes) is not evidence of an older host: the plugin's requires_hermes
    floor already guarantees the hook wherever Hermes loads it, so the hook is registered there."""
    mod = sys.modules.get(HOST_MODULE)
    return mod is not None and not host_knows(hook_name)


def register(ctx, clock: Callable[[], float] = time.time) -> None:
    """Register the hook unless a loaded host lacks its name (then one content-free line). Never raises."""
    if host_lacks(HOOK_NAME):
        logger.info(NO_HOST)
        return
    try:
        ctx.register_hook(HOOK_NAME, make_transform_tool_result(clock=clock))
    except Exception:  # noqa: BLE001 - a host's hook API must never break plugin registration
        logger.warning(HOST_FAILED)


MODALITY = "derived"
HOOK_UNKNOWN = "unknown: this host has no transform_tool_result hook"
_WORDS = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def _globs_in_words(n: int, noun: str = "glob") -> str:
    if n <= 0:
        return f"no {noun}s"
    if n == 1:
        return f"one {noun}"
    return f"{_WORDS[n - 1]} {noun}s" if n <= len(_WORDS) else f"many {noun}s"


def label(globs: tuple, opt_in: bool, known: bool) -> str:
    if not globs:
        return "result filter off: no health tools listed"
    if opt_in:
        return "result filter off: raw numbers opted in"
    on = f"result filter on: {_globs_in_words(len(globs), 'tool glob')}"
    return on if known else on + ", but this host has no result hook"


def tool(env: Optional[Mapping[str, str]] = None, home=None) -> dict:
    """limitless_result_tier: the filter's state in words. Read-only; never names a glob."""
    globs, opt_in = settings(config(env, home))
    known = host_knows(HOOK_NAME)
    value = {"filter": "on" if globs and not opt_in else "off", "tool_globs": _globs_in_words(len(globs)),
             "raw_numbers_opt_in": "on" if opt_in else "off", "host_hook": "known" if known else HOOK_UNKNOWN}
    return {"value": value, "modality": MODALITY, "age_h": None, "evidence_tier": "direct",
            "label": {"label": label(globs, opt_in, known), "tier": "T1", "modality": MODALITY}}
