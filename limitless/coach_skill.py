"""The plugin's own skills, ``limitless:coach``, ``limitless:learn`` and ``limitless:chief`` (skills/<name>/SKILL.md),
offered to the host.

NAMES is the small tuple of skill names; each one's text is ``skills/<name>/SKILL.md`` (``path(name)``).

Host registration (plugin.register): a host ctx with a callable ``register_skill`` (HOST_METHOD; Hermes
``register_skill(name, path, description="", frontmatter=None)``, resolvable as ``'<plugin_name>:<name>'`` via
skill_view) gets one call per name, ``register_skill(name, path(name), description=...)``, with the description
read from that skill's own frontmatter. A host without it (an older Hermes) gets nothing and one content-free
line in all, NO_HOST; a call that raises (a bad name, a missing file, anything) gets one content-free line,
HOST_FAILED, and the next skill and the plugin's other registrations go on. The skills are read-only text:
they add no tool, no job and no write. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

NAMES = ("coach", "learn", "chief")
HOST_METHOD = "register_skill"   # the host ctx method register looks for (feature detection)
SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"
NO_HOST = "limitless: the host has no skill registration; the plugin's skills are not registered"
HOST_FAILED = "limitless: the host's skill registration failed; register went on"


def path(name: str) -> Path:
    """``skills/<name>/SKILL.md`` under SKILLS_DIR."""
    return SKILLS_DIR / name / "SKILL.md"


def description(skill_path: Path) -> str:
    """The ``description`` from the skill's flat YAML frontmatter, quotes stripped; "" when unreadable."""
    try:
        lines = Path(skill_path).read_text().split("\n")
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
    """Offer each skill in NAMES to a host that has register_skill; one failing skill never stops the next;
    never raises."""
    method = getattr(ctx, HOST_METHOD, None)
    if not callable(method):
        logger.info(NO_HOST)
        return
    for name in NAMES:
        p = path(name)
        try:
            method(name, p, description=description(p))
        except Exception:  # noqa: BLE001 - a host's skill API must never break plugin registration
            logger.warning(HOST_FAILED)
