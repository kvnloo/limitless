"""Push sender: the Hermes profile and target bin/kevin-push sends through, and whether that profile can exist.

    profile(cfg, env) / target(cfg, env)   # env var > config key > the default, as kevin-push uses them
    hermes_root(env)                       # the Hermes home the Hermes CLI resolves ``-p`` against
    check(cfg, env, hermes_home=None)      # "set: ..." / "broken: ..." / "unknown: <reason>", words only

kevin-push runs ``hermes -p <profile> send --to <target>``. The profile is ``$KEVIN_PUSH_PROFILE``, else config
``push_profile``, else PROFILE_DEFAULT; the target is ``$KEVIN_PUSH_TO``, else config ``push_to``, else
TARGET_DEFAULT. A blank or non-string value is skipped. When the profile is removed every send fails with a
non-zero rc that is only logged, so ``check`` says, from files alone, whether ``-p <profile>`` can resolve: the
profile is ``default``, or ``<Hermes home>/profiles/<profile>`` is a directory. It never runs hermes, never
starts a process and never sends. Its words never hold the profile name, the target, a path or a digit.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Mapping, Optional

PROFILE_ENV, TARGET_ENV = "KEVIN_PUSH_PROFILE", "KEVIN_PUSH_TO"
PROFILE_CONFIG, TARGET_CONFIG = "push_profile", "push_to"
PROFILE_DEFAULT = "intake"            # the Hermes profile that owns the Telegram bot
TARGET_DEFAULT = "telegram:kevin"     # a contact alias, not a chat id

SET = "set: the sender profile exists"
BROKEN = "broken: the sender profile does not exist"
UNKNOWN_PREFIX = "unknown: "
NO_HOME = UNKNOWN_PREFIX + "no Hermes home is set (HERMES_HOME or HOME)"
HOME_MISSING = UNKNOWN_PREFIX + "the Hermes home does not exist"
HOME_UNREADABLE = UNKNOWN_PREFIX + "the Hermes home cannot be read"

# hermes_constants.PROFILE_ID_RE: the only names Hermes resolves under profiles/ (others fail before a send).
PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _pick(cfg, env: Mapping[str, str], env_key: str, cfg_key: str, default: str) -> str:
    for v in (env.get(env_key), cfg.get(cfg_key) if isinstance(cfg, Mapping) else None):
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default


def profile(cfg: Optional[Mapping], env: Optional[Mapping[str, str]] = None) -> str:
    """The sender profile: $KEVIN_PUSH_PROFILE, else config ``push_profile``, else PROFILE_DEFAULT."""
    return _pick(cfg, os.environ if env is None else env, PROFILE_ENV, PROFILE_CONFIG, PROFILE_DEFAULT)


def target(cfg: Optional[Mapping], env: Optional[Mapping[str, str]] = None) -> str:
    """The send target: $KEVIN_PUSH_TO, else config ``push_to``, else TARGET_DEFAULT."""
    return _pick(cfg, os.environ if env is None else env, TARGET_ENV, TARGET_CONFIG, TARGET_DEFAULT)


def hermes_root(env: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    """The Hermes home that ``hermes -p <name>`` resolves named profiles under, for a process started with
    ``env``; None when neither HERMES_HOME nor HOME is set.

    Mirrors NousResearch/hermes-agent: hermes_cli/profiles.py ``resolve_profile_env`` (called from
    hermes_cli/main.py ``_apply_profile_override`` for ``-p``) takes the root from
    ``profile_root_for_env_home(os.environ["HERMES_HOME"], _get_default_hermes_home())``: an exported HERMES_HOME
    of the shape ``<root>/profiles/<name>`` is ``<root>``, any other value is itself (user and env syntax
    expanded, hermes_constants ``_expand_hermes_home``), and unset is the platform default
    (hermes_constants ``_platform_default_hermes_home``: ``~/.hermes`` plus ``$HERMES_DATA_DIR_SUFFIX``).
    The named profile is then ``<root>/profiles/<name>``; ``default`` is the root itself.
    """
    env = os.environ if env is None else env
    raw = (env.get("HERMES_HOME") or "").strip()
    user = (env.get("HOME") or "").strip()
    if raw:
        if raw == "~" or raw.startswith("~/"):
            if not user:
                return None
            raw = user + raw[1:]
        path = Path(os.path.expandvars(raw))
        return path.parent.parent if path.parent.name == "profiles" else path
    if not user:
        return None
    return Path(user) / (".hermes" + env.get("HERMES_DATA_DIR_SUFFIX", ""))


def check(cfg: Optional[Mapping], env: Optional[Mapping[str, str]] = None,
          hermes_home: "Path | str | None" = None) -> str:
    """Whether kevin-push's sender profile can exist, from files only: SET when it is ``default`` (any case,
    Hermes' normalize_profile_name) or ``<hermes_home>/profiles/<name lowercased>`` is a directory; BROKEN when
    the Hermes home exists and that directory does not, or the name is one Hermes never resolves; else an
    ``unknown: <reason>`` (no home known, the home does not exist or cannot be read). ``hermes_home`` defaults
    to hermes_root(env). Never runs hermes or any process; the words never hold a name, a target or a path."""
    env = os.environ if env is None else env
    name = profile(cfg, env).lower()
    if name.casefold() == "default":
        return SET
    root = Path(hermes_home) if hermes_home is not None else hermes_root(env)
    if root is None:
        return NO_HOME
    try:
        if not root.is_dir():
            return HOME_MISSING
        if not PROFILE_ID.match(name):
            return BROKEN
        return SET if (root / "profiles" / name).is_dir() else BROKEN
    except (OSError, ValueError):
        return HOME_UNREADABLE
