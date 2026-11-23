"""The plugin's own coach skill, ``limitless:coach`` (skills/coach/SKILL.md), offered to the host.

Host registration (plugin.register): a host ctx with a callable ``register_skill`` (HOST_METHOD; Hermes
``register_skill(name, path, description="", frontmatter=None)``, resolvable as ``'<plugin_name>:<name>'`` via
skill_view) gets one call, ``register_skill("coach", PATH, description=...)``, with the description read from
the skill's own frontmatter. A host without it (an older Hermes) gets nothing and one content-free line,
NO_HOST; a host that raises (a bad name, a missing file, anything) gets one content-free line, HOST_FAILED,
and the plugin's other registrations go on. The skill is read-only text: it adds no tool, no job and no
write. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

NAME = "coach"
HOST_METHOD = "register_skill"   # the host ctx method register looks for (feature detection)
PATH = Path(__file__).resolve().parents[1] / "skills" / NAME / "SKILL.md"
NO_HOST = "limitless: the host has no skill registration; the coach skill is not registered"
HOST_FAILED = "limitless: the host's skill registration failed; register went on"


def description(path: Path = None) -> str:
    """The ``description`` from the skill's flat YAML frontmatter, quotes stripped; "" when unreadable."""
    try:
        lines = Path(path or PATH).read_text().split("\n")
    except OSError:
        return ""
    if not lines or lines[0] != "---":
        return ""
    for ln in lines[1:]:
        if ln == "---":
            break
        key, sep, val = ln.partition(":")
        if sep and key.strip() == "description":
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            return val
    return ""


def register(ctx) -> None:
    """Offer the coach skill to a host that has register_skill; never raises."""
    method = getattr(ctx, HOST_METHOD, None)
    if not callable(method):
        logger.info(NO_HOST)
        return
    try:
        method(NAME, PATH, description=description(PATH))
    except Exception:  # noqa: BLE001 - a host's skill API must never break plugin registration
        logger.warning(HOST_FAILED)
