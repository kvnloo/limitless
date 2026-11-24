"""Push sender: the Hermes profile and target bin/kevin-push sends through, and whether that profile can exist.

    profile(cfg, env) / target(cfg, env)   # env var > (profile only: the owner's reply) > config key > default
    hermes_root(env)                       # the Hermes home the Hermes CLI resolves ``-p`` against
    check(cfg, env, hermes_home=None)      # "set: ..." / "broken: ..." / "unknown: <reason>", words only
    readiness(cfg, env, hermes_home=None)  # "ready" / "no Telegram bot token ..." / "no Telegram chat ..." /
                                           # "missing: ..." / "unknown: <reason>", words only, report-only

kevin-push runs ``hermes -p <profile> send --to <target>``. The profile is ``$KEVIN_PUSH_PROFILE``, else the
owner's ``push via <name>`` reply (REPLY_FILE ``push-sender.json`` in the state dir, written by
sender_reply.ingest only for a profile that exists and that readiness does not call NO_TOKEN or NO_CHAT), else
config ``push_profile``, else PROFILE_DEFAULT; the
target is ``$KEVIN_PUSH_TO``, else config ``push_to``, else TARGET_DEFAULT. A blank or non-string value is
skipped, and so is a reply file that is missing, broken or names no profile Hermes could resolve. When the profile is removed every send fails with a
non-zero rc that is only logged, so ``check`` says, from files alone, whether ``-p <profile>`` can resolve: the
profile is ``default``, or ``<Hermes home>/profiles/<profile>`` is a directory. It never runs hermes, never
starts a process and never sends. Its words never hold the profile name, the target, a path or a digit.
kevin-push asks ``check`` before each send: BROKEN starts no hermes and logs NO_SENDER_HOW instead (SET and
``unknown: ...`` try the send). There is never a fallback sender: choosing one is the owner's call.
``readiness`` goes one step further for limitless-doctor's "push sender" row: an existing profile can still fail
every send with no Telegram bot token in its ``.env`` / ``config.yaml`` / environment, or no chat to send to (no
home channel for a bare ``telegram`` target, no channel directory entry for a named one). It reads only whether
a key is present and non-empty, never a value; kevin-push never asks it, so a wrong guess cannot block a send.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import math
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
# kevin-push's log ``how`` for a send it did not start because check() is BROKEN (delivery_audit reads it).
NO_SENDER_HOW = "log (no sender profile)"

# hermes_constants.PROFILE_ID_RE: the only names Hermes resolves under profiles/ (others fail before a send).
PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _pick(cfg, env: Mapping[str, str], env_key: str, cfg_key: str, default: str) -> str:
    for v in (env.get(env_key), cfg.get(cfg_key) if isinstance(cfg, Mapping) else None):
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default


# The owner's "push via <name>" reply, as sender_reply.ingest writes it: {"profile": name, "at": epoch}, 0600.
REPLY_FILE = "push-sender.json"


def state_dir_for(cfg: Optional[Mapping], env: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    """The limitless state dir as state_reader.state_dir picks it: $LIMITLESS_STATE, else config ``state``, else
    ``$HOME/.local/state/limitless``; None when none of them is set (then no reply file is read)."""
    env = os.environ if env is None else env
    if isinstance(env.get("LIMITLESS_STATE"), str) and env["LIMITLESS_STATE"]:
        return Path(env["LIMITLESS_STATE"])
    st = cfg.get("state") if isinstance(cfg, Mapping) else None
    if isinstance(st, str) and st:
        return Path(st)
    home = env.get("HOME")
    return Path(home) / ".local/state/limitless" if isinstance(home, str) and home.strip() else None


def reply_profile(state_dir: "Path | str | None") -> Optional[str]:
    """The profile REPLY_FILE in ``state_dir`` names (lowercased), or None when there is no state dir, no file,
    a broken one, or a name Hermes never resolves (PROFILE_ID). Never raises."""
    if state_dir is None:
        return None
    try:
        data = json.loads((Path(state_dir) / REPLY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    name = data.get("profile") if isinstance(data, dict) else None
    if not isinstance(name, str) or not PROFILE_ID.match(name.strip().lower()):
        return None
    return name.strip().lower()


def reply_at(state_dir: "Path | str | None") -> Optional[float]:
    """The epoch REPLY_FILE in ``state_dir`` records (``at``: when the owner's reply set the sender), only when the
    file also names a profile kevin-push would use (reply_profile); else None. The sender confirmation's event
    (jobs.sender_changed_verdict) reads it. Never raises; never returns the name."""
    if reply_profile(state_dir) is None:
        return None
    try:
        data = json.loads((Path(state_dir) / REPLY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    at = data.get("at") if isinstance(data, dict) else None
    if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at):
        return None
    return float(at)


def profile(cfg: Optional[Mapping], env: Optional[Mapping[str, str]] = None,
            state_dir: "Path | str | None" = None) -> str:
    """The sender profile: $KEVIN_PUSH_PROFILE, else the owner's reply (reply_profile over ``state_dir``, default
    state_dir_for(cfg, env)), else config ``push_profile``, else PROFILE_DEFAULT. The reply beats an old config
    value; the env var beats everything."""
    env = os.environ if env is None else env
    v = env.get(PROFILE_ENV)
    if isinstance(v, str) and v.strip():
        return v.strip()
    got = reply_profile(state_dir if state_dir is not None else state_dir_for(cfg, env))
    if got is not None:
        return got
    return _pick(cfg, {}, PROFILE_ENV, PROFILE_CONFIG, PROFILE_DEFAULT)


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


# -- readiness: can the sender profile reach Telegram (report-only; kevin-push never asks it) ----------------------

READY = "ready"
NO_TOKEN = "no Telegram bot token in the sender profile"
NO_CHAT = "no Telegram chat set for the sender profile"
MISSING = "missing: the sender profile does not exist"
NOT_TELEGRAM = UNKNOWN_PREFIX + "the send target is not a Telegram chat"
SECRET_SOURCE = UNKNOWN_PREFIX + "the sender profile may keep its Telegram bot token in a secret source"
FILES_UNREADABLE = UNKNOWN_PREFIX + "the sender profile's files cannot be read"

TOKEN_KEY, HOME_CHANNEL_KEY = "TELEGRAM_BOT_TOKEN", "TELEGRAM_HOME_CHANNEL"
# plugins/platforms/telegram/telegram_ids.py parse_send_target: "<chat id>[:<topic id>]", "<dm id>:<topic name>",
# or an @username are chats in themselves; any other ref is a name looked up in the channel directory.
_TG_EXPLICIT = (re.compile(r"^\s*-?\d+(?::\d+)?\s*$"), re.compile(r"^\s*\d+:[^:\s][^:]*?\s*$"),
                re.compile(r"^\s*@[A-Za-z0-9_]{4,32}\s*$"))
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(.*)$")
_YAML_KEY = re.compile(r"""^(\s*)(?:"([^"]+)"|'([^']+)'|([^\s#'"\-][^:]*?))\s*:(?:\s+(.*?))?\s*$""")
_REF = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*))?\}$")


def _text(path: Path) -> Optional[str]:
    """The file's text (utf-8, a BOM dropped, latin-1 on bad bytes), or None when there is no such file.
    Raises OSError when it exists but cannot be read."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except IsADirectoryError:
        raise PermissionError("not a file") from None
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _scalar(raw: str) -> str:
    """A dotenv / YAML scalar as its loader sees it: quotes removed, an unquoted `` #`` comment dropped."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    if raw and raw[0] in "'\"" and raw[0] in raw[1:]:
        return raw[1:raw.index(raw[0], 1)]
    return re.split(r"\s#", raw, maxsplit=1)[0].strip() if not raw.startswith("#") else ""


def _dotenv_filled(text: Optional[str]) -> dict:
    """{name: whether its value is non-empty} for one dotenv file; the values themselves are dropped here."""
    out = {}
    for line in (text or "").splitlines():
        m = _ENV_LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return {k: _scalar(v) for k, v in out.items()}


def _yaml_blocks(text: Optional[str]) -> dict:
    """The block mappings of a plain config.yaml as nested dicts of strings. Lists are skipped; flow and
    multi-line values stay raw strings. Enough for the few keys readiness asks about; never raises."""
    root: dict = {}
    stack = [(-1, root)]
    list_at = None
    for line in (text or "").splitlines():
        body = line.lstrip(" ")
        if not body.strip() or body.startswith("#"):
            continue
        indent = len(line) - len(body)
        if list_at is not None and (indent > list_at or body.startswith("-")):
            continue
        list_at = None
        if body.startswith("-"):
            list_at = indent
            continue
        m = _YAML_KEY.match(line)
        if not m:
            continue
        key = m.group(2) or m.group(3) or m.group(4)
        while indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        value = m.group(5)
        if value is None or value == "" or value.startswith("#"):
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _scalar(value)
    return root


def _filled(value, lookup) -> bool:
    """Whether a value is non-empty once a whole ``${VAR}`` / ``${VAR:-default}`` reference is expanded."""
    if not isinstance(value, str) or not value.strip():
        return False
    m = _REF.match(value.strip())
    if not m:
        return True
    return lookup(m.group(1)) or bool((m.group(2) or "").strip())


def _profile_home(cfg, env: Mapping[str, str], hermes_home) -> Optional[Path]:
    name = profile(cfg, env).lower()
    root = Path(hermes_home) if hermes_home is not None else hermes_root(env)
    if root is None:
        return None
    return root if name.casefold() == "default" else root / "profiles" / name


def _directory_has(home: Path, name: str) -> bool:
    """gateway/channel_directory.py resolve_channel_name for Telegram over ``channel_directory.json`` with
    ``channel_aliases.json`` laid over it: an id, a name or ``name (type)`` label (case and a leading ``#``
    ignored), or an unambiguous name prefix. A broken JSON file reads as empty, as Hermes reads it."""
    def load(fname):
        text = _text(home / fname)
        try:
            data = json.loads(text) if text else {}
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {}

    platforms = load("channel_directory.json").get("platforms")
    entries = platforms.get("telegram") if isinstance(platforms, dict) else None
    entries = [dict(e) for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    aliases = load("channel_aliases.json").get("telegram")
    for chat_id, friendly in (aliases.items() if isinstance(aliases, dict) else ()):
        if isinstance(friendly, str) and friendly.strip():
            hits = [e for e in entries if e.get("id") == str(chat_id)]
            for e in hits:
                e["name"] = friendly.strip()
            if not hits:
                entries.append({"id": str(chat_id), "name": friendly.strip(), "type": "dm"})
    norm = lambda v: str(v).lstrip("#").strip().lower()  # noqa: E731
    raw, query = name.strip(), norm(name)
    named = [e for e in entries if isinstance(e.get("name"), str)]
    if any(e.get("id") == raw for e in entries):
        return True
    for e in named:
        label = f"{e['name']} ({e['type']})" if e.get("type") else e["name"]
        if query in (norm(e["name"]), norm(label)):
            return True
    return len([e for e in named if norm(e["name"]).startswith(query)]) == 1


def readiness(cfg: Optional[Mapping], env: Optional[Mapping[str, str]] = None,
              hermes_home: "Path | str | None" = None) -> str:
    """Whether ``hermes -p <profile> send --to <target>`` (kevin-push's delivery) has what it needs, from the
    sender profile's files only: READY, NO_TOKEN, NO_CHAT, MISSING (check is BROKEN), or ``unknown: ...``
    (check's unknowns, a target that is not Telegram, a token that may sit in a secret source, files that cannot
    be read). Report-only: kevin-push's preflight asks check, never this, so a wrong answer cannot block a send.

    Mirrors NousResearch/hermes-agent: hermes_cli/send_cmd.py ``_load_hermes_env`` loads ``<profile home>/.env``
    over the process env (override) and bridges top-level ``config.yaml`` scalars into it where unset;
    plugins/platforms/telegram/gateway_env.py takes the token from ``TELEGRAM_BOT_TOKEN`` (or
    ``platforms.telegram.token``) and the home channel from ``TELEGRAM_HOME_CHANNEL`` (or
    ``platforms.telegram.home_channel.chat_id``); gateway/outbound/send.py sends a bare ``telegram`` target to
    the home channel, and gateway/outbound/targets.py takes a chat id or @username as is and looks any other
    name up in the channel directory. Only presence is read: a value never leaves this function, and the words
    never hold a value, the profile name, the target, a path or a digit. Never runs hermes or any process.
    """
    env = os.environ if env is None else env
    exists = check(cfg, env, hermes_home)
    if exists == BROKEN:
        return MISSING
    if exists != SET:
        return exists
    platform, _, ref = target(cfg, env).partition(":")
    if platform.strip().lower() != "telegram":
        return NOT_TELEGRAM
    home = _profile_home(cfg, env, hermes_home)
    try:
        dotenv = _dotenv_filled(_text(home / ".env"))
        conf = _yaml_blocks(_text(home / "config.yaml"))

        def lookup(key: str) -> bool:
            if key in dotenv:
                return _filled(dotenv[key], lambda k: isinstance(env.get(k), str) and bool(env[k].strip()))
            if isinstance(env.get(key), str):
                return bool(env[key].strip())
            return _filled(conf.get(key), lambda k: False)

        tg = (conf.get("platforms") or {}).get("telegram") if isinstance(conf.get("platforms"), dict) else None
        tg = tg if isinstance(tg, dict) else {}
        if not (lookup(TOKEN_KEY) or _filled(tg.get("token"), lookup)):
            secrets = conf.get("secrets")
            if isinstance(secrets, dict) and any(isinstance(v, dict) for v in secrets.values()):
                return SECRET_SOURCE
            return NO_TOKEN
        ref = ref.strip()
        if not ref:
            hc = tg.get("home_channel")
            if isinstance(hc, dict):
                has_home = _filled(hc.get("chat_id"), lookup)
            else:
                has_home = isinstance(hc, str) and bool(re.search(r"chat_id\s*:\s*['\"]?[^\s,'\"}]", hc))
            return READY if lookup(HOME_CHANNEL_KEY) or has_home else NO_CHAT
        if any(p.match(ref) for p in _TG_EXPLICIT):
            return READY
        return READY if _directory_has(home, ref) else NO_CHAT
    except (OSError, ValueError):
        return FILES_UNREADABLE
