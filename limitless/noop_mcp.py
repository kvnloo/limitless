"""The NOOP agent MCP server (stdio; health read tools such as health_snapshot, sleep_summary, data_freshness), as
config the person hands to the host by hand.

    server_spec(cfg) -> {"name", "command", "env"} | None
    covered(spec, cfg) -> bool
    state(cfg) -> OFF | MALFORMED | REFUSED | BY_HAND

Config ``noop_mcp`` is ``{"command": [executable, arg, ...], "env": {NAME: value}, "name": "noop"}``: ``command``
a non-empty list of non-empty strings, ``env`` an optional map of strings, ``name`` the optional key the person
gives it under the host's ``mcp_servers`` (default ``noop``). Unset is None: the feature is off by default.
Anything else is None too, and ``state`` calls it MALFORMED.

The host names an MCP tool ``mcp__<server>__<tool>`` with every character outside ``[A-Za-z0-9_]`` turned into
``_`` (hermes-agent ``tools/mcp_tool_schema.py``, ``mcp_prefixed_tool_name``), so ``tool_prefix`` is
``mcp__<name>__``. ``covered`` is true only when one glob of the result tier filter (config ``t0_tools``,
result_tier.settings) matches every tool under that prefix: the known tool names and a made-up one, so a glob for
one tool or one family is not enough. Without that, the server's raw readings would reach context unfiltered.

Hermes has no plugin API to register an MCP server: the plugin context has none, the published plugin API lists
none, and only a portable package without Python code can ship a static ``mcp.json`` (see docs/noop-mcp.md). So
this module registers nothing; it only says what the person must add to ``mcp_servers`` and whether that is safe
(the limitless-doctor row). It never starts, stops or calls a process. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import re
from fnmatch import fnmatchcase
from typing import Mapping, Optional

from . import result_tier

KEY = "noop_mcp"
DEFAULT_NAME = "noop"
KNOWN_TOOLS = ("health_snapshot", "sleep_summary", "data_freshness")
PROBE_TOOL = "any_other_tool"   # a made-up name: a covering glob must match tools not listed yet

OFF, MALFORMED, REFUSED, BY_HAND = "off", "malformed", "refused", "by_hand"


def _strs(items) -> bool:
    return isinstance(items, list) and bool(items) and all(isinstance(s, str) and s for s in items)


def is_set(cfg) -> bool:
    """True when config holds a non-null ``noop_mcp``, well formed or not."""
    return isinstance(cfg, Mapping) and cfg.get(KEY) is not None and cfg.get(KEY) != {}


def server_spec(cfg) -> Optional[dict]:
    """``{"name", "command", "env"}`` (copies) from config ``noop_mcp``; None when unset or malformed."""
    if not is_set(cfg):
        return None
    raw = cfg[KEY]
    if not isinstance(raw, Mapping) or not _strs(raw.get("command")):
        return None
    env = raw.get("env", {})
    if not isinstance(env, Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        return None
    name = raw.get("name", DEFAULT_NAME)
    if not isinstance(name, str) or not name.strip():
        return None
    return {"name": name.strip(), "command": list(raw["command"]), "env": dict(env)}


def tool_prefix(spec: Mapping) -> str:
    """``mcp__<name>__``, the host's prefix for this server's tools."""
    return "mcp__" + re.sub(r"[^A-Za-z0-9_]", "_", spec["name"]) + "__"


def covered(spec, cfg) -> bool:
    """True when one t0_tools glob matches every tool under the server's prefix (known and made-up names)."""
    if not spec:
        return False
    globs, _ = result_tier.settings(cfg)
    names = [tool_prefix(spec) + t for t in KNOWN_TOOLS + (PROBE_TOOL,)]
    return any(all(fnmatchcase(n, g) for n in names) for g in globs)


def state(cfg) -> str:
    """OFF (unset), MALFORMED, REFUSED (t0_tools does not cover its tools) or BY_HAND (safe to add by hand)."""
    if not is_set(cfg):
        return OFF
    spec = server_spec(cfg)
    if spec is None:
        return MALFORMED
    return BY_HAND if covered(spec, cfg) else REFUSED
