"""Focus safe: an agent's phone or desktop automation runs on an agent display, never on the person's screen.

    classify(tool_name, args, serials=(), agent_displays=()) -> {"verdict": "ok" | "warn", "why": str}

Pure and advisory. A shell-like tool (SHELL_TOOLS; the command in ``command`` or ``cmd``) whose command
drives a foreground UI the person is using is ``warn``; everything else is ``ok``. The rules are the RULES
table (docs/focus-safe.md shows it): adb ``input`` gestures and ``am start`` on a protected phone that do not
name an agent display, xdotool and wmctrl that do not run on an agent ``DISPLAY``, and osascript activate or
keystroke, ``open -a`` without ``-g`` and cliclick, which have no agent display at all. Read-only commands
(``dumpsys``, ``uiautomator dump``, ``screencap``, ``getprop``, ``xdotool getactivewindow`` ...) match no rule.

The protected adb serials and the agent display ids come only from the caller (config ``focus_safe_serials``
and ``focus_safe_agent_displays``, read by the hook); with neither set the guard is inert: ``ok`` with the
reason ``no protected devices set``. A phone rule applies only when protected serials are set; an adb call
that names no serial (no ``-s``, no ``ANDROID_SERIAL``) may pick a protected phone and is read as one. Display
``0`` is the default display and is never an agent display. Every ``why`` is plain and digit-free and never
names a serial or a display id. Nothing here runs a command, reads config or raises: a command that cannot be
read is ``ok``.

The hook (make_pre_tool_call, registered for Hermes ``pre_tool_call``) is off unless config ``focus_safe`` is
``"warn"``. The Hermes contract (hermes_cli/plugins.py ``_get_pre_tool_call_directive_details``) reads only
``block``, ``approve`` and ``modify`` returns and has no way to add a note, so the hook always returns None:
it never blocks (Hermes approvals own that) and never rewrites args. On a warn it records the plain note
(``note``) as one content-free tier_audit line, hook HOOK (counts and a hash, never the note or the command;
nothing when the audit is off). Any exception is ok: a raising pre_tool_call callback would block the call,
so the hook catches everything. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import os
import shlex
import time
from typing import Callable, Iterable, List, Mapping, Optional, Tuple

from . import tier_audit
from .state_reader import config

OK, WARN = "ok", "warn"
MODE_KEY, SERIALS_KEY, DISPLAYS_KEY = "focus_safe", "focus_safe_serials", "focus_safe_agent_displays"
OFF = "off"
HOOK = "pre_tool_call:focus_safe"
INERT = "no protected devices set"
NOTHING = "no foreground UI command"
UNREADABLE = "command not readable"
SHELL_TOOLS = frozenset({"terminal", "shell", "bash", "run_command", "execute_command"})
ARG_KEYS = ("command", "cmd")
DEFAULT_DISPLAY = "0"

# The rule table: what each rule watches (drives), when the same command is fine (ok_when) and the plain
# words an agent sees (why). First match wins; a command matching no rule is ok.
RULES = (
    {"id": "adb-input", "drives": "adb shell input tap, swipe, text, keyevent, press or roll on a protected phone",
     "ok_when": "input -d names an agent display, or adb -s names a phone that is not protected",
     "why": "adb input on a protected phone, not on an agent display: it moves the person's screen"},
    {"id": "adb-am-start", "drives": "adb shell am start on a protected phone",
     "ok_when": "am start --display names an agent display, or adb -s names a phone that is not protected",
     "why": "am start on a protected phone, not on an agent display: it opens an app over the person's screen"},
    {"id": "xdotool", "drives": "xdotool key, type, mouse moves, clicks, window activate or focus",
     "ok_when": "DISPLAY names an agent display",
     "why": "xdotool drives the person's desktop, not an agent display"},
    {"id": "wmctrl", "drives": "wmctrl -a, -R or -s (activate a window, switch desktop)",
     "ok_when": "DISPLAY names an agent display",
     "why": "wmctrl moves the person's focus to another window or desktop"},
    {"id": "osascript", "drives": "osascript with activate, keystroke, key code or click",
     "ok_when": "never: the desktop has no agent display",
     "why": "osascript brings an app forward or types into the person's desktop"},
    {"id": "open-app", "drives": "open -a or open -b (bring an app forward)",
     "ok_when": "open -g (the app opens in the background)",
     "why": "open brings an app to the front of the person's desktop"},
    {"id": "cliclick", "drives": "cliclick (any mouse or key event)",
     "ok_when": "never: the desktop has no agent display",
     "why": "cliclick moves the person's mouse or types on their desktop"},
)
_WHY = {r["id"]: r["why"] for r in RULES}

_INPUT_DRIVES = frozenset({"tap", "swipe", "text", "keyevent", "press", "roll", "draganddrop", "motionevent",
                           "keycombination"})
_AM_DRIVES = frozenset({"start", "start-activity"})
_XDOTOOL_DRIVES = frozenset({"key", "keydown", "keyup", "type", "mousemove", "mousemove_relative", "click",
                             "mousedown", "mouseup", "windowactivate", "windowfocus", "windowraise", "windowmap",
                             "set_desktop", "set_desktop_for_window"})
_WRAPPERS = frozenset({"sudo", "env", "command", "exec", "nohup", "time"})
_ADB_VALUE_OPTS = frozenset({"-s", "-t", "-H", "-P", "-L"})
_OSA_WORDS = ("activate", "keystroke", "key code", "click")
_SEPARATORS = set(";&|()")


def _segments(command: str) -> List[List[str]]:
    """The command split into simple commands at ; & | ( ), each a list of words (shell quoting honoured)."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
    lex.whitespace_split = True
    out, cur = [], []
    for tok in lex:
        if tok and set(tok) <= _SEPARATORS:
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        out.append(cur)
    return out


def _assignment(tok: str) -> Optional[tuple]:
    name, eq, value = tok.partition("=")
    return (name, value) if eq and name.isidentifier() else None


def _program(words: List[str], env: dict) -> List[str]:
    """``words`` without leading NAME=value assignments (kept in ``env``) and wrappers such as sudo or env."""
    i = 0
    while i < len(words):
        a = _assignment(words[i])
        if a:
            env[a[0]] = a[1]
        elif os.path.basename(words[i]) in _WRAPPERS or words[i].startswith("-") and i and \
                os.path.basename(words[i - 1]) in _WRAPPERS:
            pass
        else:
            break
        i += 1
    return words[i:]


def _on_agent_display(display: Optional[str], agent_displays: frozenset) -> bool:
    return display is not None and display != DEFAULT_DISPLAY and display in agent_displays


def _flag(words: List[str], names: Iterable[str]) -> Optional[str]:
    names = tuple(names)
    for i, w in enumerate(words):
        if w in names and i + 1 < len(words):
            return words[i + 1]
        for n in names:
            if n.startswith("--") and w.startswith(n + "="):
                return w[len(n) + 1:]
    return None


def _device_rule(words: List[str], agent_displays: frozenset) -> Optional[str]:
    """The rule a command run on the phone (after ``adb shell``) matches, if any."""
    if not words:
        return None
    prog, rest = os.path.basename(words[0]), words[1:]
    if prog == "input":
        sub = next((w for w in rest if w in _INPUT_DRIVES), None)
        if sub and not _on_agent_display(_flag(rest[:rest.index(sub)], ("-d",)), agent_displays):
            return "adb-input"
    elif prog == "am" and rest and rest[0] in _AM_DRIVES:
        if not _on_agent_display(_flag(rest, ("--display",)), agent_displays):
            return "adb-am-start"
    return None


def _adb_rule(words: List[str], env: dict, serials: frozenset, agent_displays: frozenset) -> Optional[str]:
    if not serials:
        return None
    serial, i = env.get("ANDROID_SERIAL") or None, 1
    while i < len(words) and words[i].startswith("-"):
        if words[i] in _ADB_VALUE_OPTS and i + 1 < len(words):
            if words[i] == "-s":
                serial = words[i + 1]
            i += 2
        else:
            i += 1
    if serial is not None and serial not in serials:
        return None
    if i >= len(words) or words[i] not in ("shell", "exec-out"):
        return None
    inner = " ".join(words[i + 1:])  # adb joins its shell words with spaces; the phone's shell splits again
    shell_env: dict = {}
    for seg in _segments(inner):
        rule = _device_rule(_program(seg, shell_env), agent_displays)
        if rule:
            return rule
    return None


def _desktop_rule(prog: str, rest: List[str], env: dict, agent_displays: frozenset) -> Optional[str]:
    on_agent = _on_agent_display(env.get("DISPLAY"), agent_displays)
    if prog == "xdotool":
        return None if on_agent or not any(w in _XDOTOOL_DRIVES for w in rest) else "xdotool"
    if prog == "wmctrl":
        return None if on_agent or not any(w in ("-a", "-R", "-s") for w in rest) else "wmctrl"
    if prog == "osascript":
        text = " ".join(rest).lower()
        return "osascript" if any(w in text for w in _OSA_WORDS) else None
    if prog == "open":
        flags = "".join(w[1:] for w in rest if w.startswith("-") and not w.startswith("--"))
        return "open-app" if ("a" in flags or "b" in flags) and "g" not in flags else None
    if prog == "cliclick":
        return "cliclick"
    return None


def _command(tool_name, args) -> Optional[str]:
    if tool_name not in SHELL_TOOLS or not isinstance(args, Mapping):
        return None
    for k in ARG_KEYS:
        if isinstance(args.get(k), str):
            return args[k]
    return None


def classify(tool_name, args, serials: Iterable[str] = (), agent_displays: Iterable[str] = ()) -> dict:
    """``{"verdict": "ok" | "warn", "why"}`` for one tool call; never raises."""
    try:
        serials = frozenset(str(s) for s in (serials or ()) if str(s).strip())
        agent_displays = frozenset(str(d) for d in (agent_displays or ()) if str(d).strip())
        if not serials and not agent_displays:
            return {"verdict": OK, "why": INERT}
        command = _command(tool_name, args)
        if command is None:
            return {"verdict": OK, "why": NOTHING}
        try:
            segments = _segments(command)
        except ValueError:
            return {"verdict": OK, "why": UNREADABLE}
        env: dict = {}
        for seg in segments:
            if seg and seg[0] == "export":
                for a in filter(None, map(_assignment, seg[1:])):
                    env[a[0]] = a[1]
                continue
            seg_env = dict(env)
            words = _program(seg, seg_env)
            if not words:
                env.update(seg_env)  # a bare NAME=value sets it for the rest of the command
                continue
            prog = os.path.basename(words[0])
            rule = (_adb_rule(words, seg_env, serials, agent_displays) if prog == "adb"
                    else _desktop_rule(prog, words[1:], seg_env, agent_displays))
            if rule:
                return {"verdict": WARN, "why": _WHY[rule]}
        return {"verdict": OK, "why": NOTHING}
    except Exception:  # noqa: BLE001 - advisory: anything unexpected is ok
        return {"verdict": OK, "why": UNREADABLE}


def _ids(v) -> tuple:
    """Config ids as strings: a list of strings or numbers (or one string); anything else is none."""
    items = [v] if isinstance(v, str) else v if isinstance(v, (list, tuple)) else []
    return tuple(str(x).strip() for x in items
                 if isinstance(x, (str, int)) and not isinstance(x, bool) and str(x).strip())


def settings(cfg) -> Tuple[str, tuple, tuple]:
    """``(mode, serials, agent_displays)`` from host config; mode is ``warn`` or ``off`` (the default)."""
    if not isinstance(cfg, Mapping):
        return OFF, (), ()
    mode = cfg.get(MODE_KEY)
    mode = WARN if isinstance(mode, str) and mode.strip().lower() == WARN else OFF
    return mode, _ids(cfg.get(SERIALS_KEY)), _ids(cfg.get(DISPLAYS_KEY))


def note(why: str) -> str:
    """The one plain note for the agent on a warn."""
    return f"focus safe: {why}. Run it on an agent display, or ask the person first."


def make_pre_tool_call(clock: Callable[[], float] = time.time) -> Callable:
    """The Hermes ``pre_tool_call`` callback: advisory, always returns None, never raises."""
    def pre_tool_call(tool_name: str = "", args=None, **kwargs) -> None:
        try:
            mode, serials, displays = settings(config())
            if mode != WARN:
                return None
            got = classify(tool_name, args, serials, displays)
            if got.get("verdict") == WARN:
                tier_audit.record(tier_audit.event(HOOK, note(got["why"]), False, clock()))
        except Exception:  # noqa: BLE001 - fail open: a raising pre_tool_call would block the call
            pass
        return None
    return pre_tool_call
