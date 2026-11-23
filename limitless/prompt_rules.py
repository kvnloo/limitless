"""The plugin's standing rules as one static system prompt section, ``limitless.rules``.

The coach skill (skills/coach/SKILL.md) holds the full contract but loads only when an agent opens it, and the
per-turn state card (card.py) carries data labels, not rules. This section puts the rules themselves, in eight
short lines, into every new session's system prompt, so any agent in the profile stays inside them.

CONTENT is a constant: it reads no state, no config and no clock, holds no digit (so it is T1 by the
tier_audit rule), no clock time and no host data, and is the same bytes every session (prompt-cache
friendly). The state card stays the only data path. Every rule line has a matching rule in the coach skill
(tests/test_prompt_rules.py checks there is no drift). Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import logging
from typing import Optional

from .state_reader import config

logger = logging.getLogger(__name__)

SECTION_ID = "limitless.rules"
MAX_CHARS = 800   # the host's cap for the section; CONTENT stays well under it
POSITION = "after_memory"
CONFIG_KEY = "prompt_rules"   # default on; false (or "off") registers nothing
DISABLED = "limitless: prompt_rules is off in config; the rules section is not registered"

CONTENT = "\n".join((
    "Limitless plugin rules (they hold in every turn):",
    "- Quote the tools' labels, not raw numbers, unless the person opted in.",
    "- A null value is unknown: unknown is never zero and never a no.",
    "- Explain, suggest and prepare; commit only on the person's yes in this turn.",
    "- One habit a week; a skipped day is unlogged, never a miss.",
    "- Cues are events, never a clock time.",
    "- Nudges go only through the plugin's own jobs and send gate; never schedule one yourself.",
    "- Never advise on drugs, medicines, vitamins or amounts to take; never diagnose; no capability score.",
    "- For coaching, open the limitless:coach skill.",
))


def content() -> str:
    """The section text: always the same constant object."""
    return CONTENT


def enabled(cfg: dict) -> bool:
    """On unless config ``prompt_rules`` is false or \"off\"."""
    v = cfg.get(CONFIG_KEY, True) if isinstance(cfg, dict) else True
    return not (v is False or (isinstance(v, str) and v.strip().lower() in ("off", "false")))


def register(ctx, cfg: Optional[dict] = None) -> None:
    """Offer the rules section to the host, unless config turns it off."""
    if not enabled(config() if cfg is None else cfg):
        logger.info(DISABLED)
        return
    ctx.register_system_prompt_section(SECTION_ID, CONTENT, position=POSITION, max_chars=MAX_CHARS)
