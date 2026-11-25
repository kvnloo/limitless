"""The operator's scheduled beacon write + copy, as text to review and paste (bin/limitless-owner-beacon
schedule --print, docs/owner-beacon.md).

    text = render(kind, python, writer, out, every, copy_to=None, dbs=(), label=DEFAULT_LABEL)

``launchd`` is one plist (``StartInterval`` = every * 60). ``systemd`` is a oneshot ``<label>.service`` and a
``<label>.timer`` (``OnBootSec``, ``OnUnitActiveSec`` = every minutes), each after a ``# <label>.<kind>`` line;
the shell line is one double-quoted ExecStart word, with backslash, double quote, ``%`` and ``$`` escaped for
systemd. Both kinds run one ``/bin/sh -c`` line: the writer (``<python> <writer> write --out <out>
[--dbs a:b]``), then, with ``copy_to``, ``scp -q -p <out> <copy_to>`` (``-p`` keeps the writer's 0600 mode
and the mtime). Every value is shell-quoted. Every host-specific value comes from the caller: nothing here
names a host, user or path, and nothing is written, loaded, enabled or run. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import os
import plistlib
import shlex
from typing import Iterable, Optional

KINDS = ("launchd", "systemd")
BOOT_DELAY = "5min"   # the first run after boot; then every --every minutes
DEFAULT_LABEL = "limitless.owner-beacon"


def _join(argv: Iterable[str]) -> str:
    return " ".join(shlex.quote(a) for a in argv)


def writer_argv(python: str, writer: str, out: str, dbs: Iterable[str] = ()) -> list:
    dbs = list(dbs)
    return [python, writer, "write", "--out", out] + (["--dbs", os.pathsep.join(dbs)] if dbs else [])


def copy_argv(out: str, copy_to: str) -> list:
    return ["scp", "-q", "-p", out, copy_to]


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
