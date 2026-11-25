"""The operator's scheduled beacon write + copy, as text to review and paste (bin/limitless-owner-beacon
schedule --print, docs/owner-beacon.md).

    text = render(kind, python, writer, out, every, copy_to=None, dbs=(), label=DEFAULT_LABEL)

``launchd`` is one plist (``StartInterval`` = every * 60). ``systemd`` is a oneshot ``<label>.service`` and a
``<label>.timer`` (``OnBootSec``, ``OnUnitActiveSec`` = every minutes), each after a ``# <label>.<kind>`` line;
the shell line is one double-quoted ExecStart word, with backslash, double quote, ``%`` and ``$`` escaped for
systemd. Both kinds run one ``/bin/sh -c`` line: the writer (``<python> <writer> write --out <out>
[--dbs a:b]``), then, with ``copy_to``, ``scp -q -p -o BatchMode=yes <out> <copy_to>`` (``-p`` keeps the
writer's 0600 mode and the mtime; BatchMode fails at once instead of waiting on a prompt). Every value is shell-quoted. Every host-specific value comes from the caller: nothing here
names a host, user or path, and nothing is written, loaded, enabled or run. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import os
import plistlib
import re
import shlex
from typing import Iterable, Optional

KINDS = ("launchd", "systemd")
MIN_EVERY, MAX_EVERY = 5, 1440      # minutes: no tighter than five, no looser than a day
LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")   # reverse-DNS style; also a plain unit file name
BOOT_DELAY = "5min"   # the first run after boot; then every --every minutes
DEFAULT_LABEL = "limitless.owner-beacon"


def refusal(values: Iterable[str], every: str, out: str, copy_to: Optional[str] = None, dbs: Iterable[str] = (),
            label: Optional[str] = None) -> Optional[str]:
    """Why these arguments are refused, in one line, or None when they are fine. ``values`` is every value
    given (a newline in any of them is refused first); ``every`` is the raw --every text."""
    if any("\n" in v or "\r" in v for v in values):
        return "a value contains a newline"
    if not (every.isascii() and every.isdigit()) or not MIN_EVERY <= int(every) <= MAX_EVERY:
        return f"--every must be a whole number of minutes from {MIN_EVERY} to {MAX_EVERY}"
    if not os.path.isabs(out):
        return "--out must be an absolute path (the job does not run in this directory or expand ~)"
    if copy_to is not None and (":" not in copy_to or copy_to.startswith("-")):
        return "--copy-to must be an scp destination like user@host:path"
    for db in dbs:
        if not os.path.isabs(db) or os.pathsep in db:
            return f"--db must be an absolute path without {os.pathsep!r}"
    if label is not None and not LABEL_RE.match(label):
        return "--label must be letters, digits, dots, dashes or underscores (like org.example.owner-beacon)"
    return None


def _join(argv: Iterable[str]) -> str:
    return " ".join(shlex.quote(a) for a in argv)


def writer_argv(python: str, writer: str, out: str, dbs: Iterable[str] = ()) -> list:
    dbs = list(dbs)
    return [python, writer, "write", "--out", out] + (["--dbs", os.pathsep.join(dbs)] if dbs else [])


def copy_argv(out: str, copy_to: str) -> list:
    # BatchMode: nobody is at a terminal when the job runs, so a password or host-key prompt fails at once.
    return ["scp", "-q", "-p", "-o", "BatchMode=yes", out, copy_to]


def shell_line(python: str, writer: str, out: str, copy_to: Optional[str] = None, dbs: Iterable[str] = ()) -> str:
    """The one /bin/sh -c line: the writer, then the copy when ``copy_to`` is given and the writer exited 0."""
    line = _join(writer_argv(python, writer, out, dbs))
    if copy_to:
        line += " && " + _join(copy_argv(out, copy_to))
    return line


def launchd(line: str, every: int, label: str) -> str:
    return plistlib.dumps({
        "Label": label,
        "ProgramArguments": ["/bin/sh", "-c", line],
        "StartInterval": every * 60,
        "RunAtLoad": True,
    }).decode("utf-8")


def systemd_word(text: str) -> str:
    """``text`` as one double-quoted systemd word that systemd unquotes back to ``text`` (no specifier or
    variable expansion)."""
    for a, b in (("\\", "\\\\"), ('"', '\\"'), ("%", "%%"), ("$", "$$")):
        text = text.replace(a, b)
    return '"' + text + '"'


def systemd(line: str, every: int, label: str) -> str:
    return (f"# {label}.service\n"
            "[Unit]\n"
            "Description=Write the owner beacon (limitless-owner-beacon) and copy it when asked\n"
            "\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart=/bin/sh -c {systemd_word(line)}\n"
            "\n"
            f"# {label}.timer\n"
            "[Unit]\n"
            f"Description=Owner beacon, every {every} minutes\n"
            "\n"
            "[Timer]\n"
            f"OnBootSec={BOOT_DELAY}\n"
            f"OnUnitActiveSec={every}min\n"
            f"Unit={label}.service\n"
            "\n"
            "[Install]\n"
            "WantedBy=timers.target\n")


def render(kind: str, python: str, writer: str, out: str, every: int, copy_to: Optional[str] = None,
           dbs: Iterable[str] = (), label: str = DEFAULT_LABEL) -> str:
    line = shell_line(python, writer, out, copy_to, dbs)
    if kind == "launchd":
        return launchd(line, every, label)
    if kind == "systemd":
        return systemd(line, every, label)
    raise ValueError(kind)
