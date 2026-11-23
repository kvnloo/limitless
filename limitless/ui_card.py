"""The state card, the week review and the skill tree as one small, glanceable HTML card (an ephemeral card, not a wall of text).

    r = render(title, lines, kind)   # {"html", "rows", "dropped", "chips"}; pure, writes nothing
    chip(line)                       # "known" | "unknown" | "held", from the line's own words
    write(out_dir, html)             # atomic, 0600, named by a content hash; the path

Deterministic code builds the card from lines the plugin already makes digit-free (card.build for the state
card, the week review body for the week, skill_tree.lines for the skill tree); the model never writes its contents. Every line goes through
tier_audit.gate (hook ``ui_card:<kind>``) with the raw opt-in always off: a line with a digit is dropped and
counted, never shown, so no raw number reaches a card even when the person opted in for prompts. Blank and
non-text lines are dropped too, and so is any line past MAX_ROWS.

The chip is read from the line's words only (UNKNOWN_WORDS first, then HELD_WORDS, else known), never from
raw data. All text is HTML-escaped. The HTML is self-contained: inline CSS only, no script, no link, no
image, no font or anything else fetched, no clock time. The layout fits a phone: no fixed width, text wraps,
nothing scrolls sideways. The one motion (rows fade in) is CSS only and is off under
``prefers-reduced-motion``. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import hashlib
import html as _html
import os
import re
import tempfile
from pathlib import Path
from typing import Iterable, Mapping, Optional

from . import tier_audit
from .state_reader import config

KINDS = ("state", "week", "skill_tree")
TITLES = {"state": "Today", "week": "This week", "skill_tree": "Skill tree"}
MAX_ROWS = 8
KNOWN, UNKNOWN, HELD = "known", "unknown", "held"
CHIPS = (KNOWN, UNKNOWN, HELD)
UNKNOWN_WORDS = ("unknown", "not recording", "no digest", "no data", "not enough", "none set")
HELD_WORDS = ("held", "hold", "holds", "waiting", "muted", "snoozed", "quiet tonight", "paused")
HOOK = "ui_card:{kind}"
ENV_KEY = "LIMITLESS_CARD_DIR"
CONFIG_KEY = "card_dir"
NO_DIR = (f"no card dir: set {ENV_KEY} or \"{CONFIG_KEY}\" in config.json to keep a card file; "
          "the card was rendered only, nothing was written")

_CSS = """
:root{color-scheme:light dark;--bg:#f3f0ea;--card:#fbfaf7;--ink:#33393d;--soft:#6f7478;--line:#e3ded5;
--known-bg:#dde7de;--known-ink:#3f5f47;--unknown-bg:#e6e3de;--unknown-ink:#66625c;
--held-bg:#efe4cf;--held-ink:#7a6136}
@media (prefers-color-scheme:dark){:root{--bg:#1f2224;--card:#272b2e;--ink:#e4e1db;--soft:#a3a6a8;
--line:#363b3e;--known-bg:#2f4236;--known-ink:#bcd3c1;--unknown-bg:#3a3a38;--unknown-ink:#c4c0b8;
--held-bg:#463c2a;--held-ink:#e0cba3}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{margin:0;padding:1rem;background:var(--bg);color:var(--ink);
font:1.25rem/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.card{max-width:100%;margin:0 auto;padding:1.1rem 1.2rem;background:var(--card);border-radius:1.1rem;
border:1px solid var(--line)}
h1{margin:0 0 .6rem;font-size:1.6rem;font-weight:600;letter-spacing:.01em;overflow-wrap:anywhere}
ul{list-style:none;margin:0;padding:0}
.row{display:flex;gap:.7rem;align-items:flex-start;padding:.7rem 0;border-top:1px solid var(--line);
animation:rise .5s ease-out both}
.row:first-child{border-top:0}
.text{flex:1 1 auto;min-width:0;overflow-wrap:anywhere}
.chip{flex:0 0 5.2rem;margin-top:.2rem;padding:.15rem .3rem;text-align:center;border-radius:99rem;font-size:.85rem;
font-weight:600;letter-spacing:.02em}
.known .chip{background:var(--known-bg);color:var(--known-ink)}
.unknown .chip{background:var(--unknown-bg);color:var(--unknown-ink)}
.held .chip{background:var(--held-bg);color:var(--held-ink)}
.empty{color:var(--soft)}
@keyframes rise{from{opacity:0;transform:translateY(.3rem)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
""".strip()


def _has(text: str, words: Iterable[str]) -> bool:
    return any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in words)


def chip(line: str) -> str:
    """The row's state chip from the line's own words: unknown (any unknown word wins), held, else known."""
    t = line.lower() if isinstance(line, str) else ""
    if _has(t, UNKNOWN_WORDS):
        return UNKNOWN
    if _has(t, HELD_WORDS):
        return HELD
    return KNOWN


def _title(title, kind: str) -> str:
    ok = isinstance(title, str) and title.strip() and not any(c.isdigit() for c in title)
    return title.strip() if ok else TITLES[kind]


def rows(lines, kind: str, env: Optional[Mapping[str, str]] = None, now: Optional[float] = None):
    """([(line, chip)], dropped): each text line through tier_audit.gate with the opt-in off, at most MAX_ROWS."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    kept, dropped = [], 0
    for ln in list(lines or ()):
        text = ln.strip() if isinstance(ln, str) else ""
        if not text:
            dropped += 1
            continue
        if tier_audit.gate(HOOK.format(kind=kind), text, False, env=env, now=now) is None:
            dropped += 1      # a digit: never in a card, even under the raw opt-in
            continue
        if len(kept) >= MAX_ROWS:
            dropped += 1
            continue
        kept.append((text, chip(text)))
    return kept, dropped


def render(title, lines, kind: str, env: Optional[Mapping[str, str]] = None, now: Optional[float] = None) -> dict:
    """{"html", "rows", "dropped", "chips"} for one card. Pure apart from the gate's content-free audit line."""
    kept, dropped = rows(lines, kind, env, now)
    def esc(s):
        return _html.escape(s, quote=False)   # text nodes only: no &#x27; entity (it would carry digits)
    name = esc(_title(title, kind))
    items = "\n".join(f'<li class="row {c}"><span class="chip">{c}</span><span class="text">{esc(t)}</span></li>'
                      for t, c in kept)
    if not items:
        items = '<li class="row unknown empty"><span class="chip">unknown</span><span class="text">nothing to show</span></li>'
    html = ("<!doctype html>\n"
            '<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<meta name="color-scheme" content="light dark"><title>{name}</title>'
            f"<style>\n{_CSS}\n</style></head>\n"
            f'<body><main class="card {esc(kind)}"><h1>{name}</h1>\n<ul>\n{items}\n</ul></main></body></html>\n')
    return {"html": html, "rows": len(kept), "dropped": dropped, "chips": kept}


def card_dir(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[Path]:
    """$LIMITLESS_CARD_DIR, else config "card_dir"; None (render only, write nothing) by default."""
    env = os.environ if env is None else env
    v = env.get(ENV_KEY) or config(env, home).get(CONFIG_KEY)
    return Path(v).expanduser() if isinstance(v, str) and v.strip() else None


def name_for(html: str) -> str:
    """The card's file name: a hash of its content, never a date or a clock time."""
    return "card-" + hashlib.sha256(html.encode("utf-8")).hexdigest()[:16] + ".html"


def write(out_dir, html: str) -> Optional[str]:
    """Write ``html`` to ``out_dir``/name_for(html) atomically (temp file in out_dir, mode 0600, fsync, rename);
    the path as a string. No ``out_dir`` writes nothing and returns None. The same card always gets the same
    name, so writing it again replaces it in place. A failed write leaves no temp file and raises."""
    if out_dir is None or (isinstance(out_dir, str) and not out_dir.strip()):
        return None
    d = Path(out_dir)
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = d / name_for(html)
    fd, tmp = tempfile.mkstemp(prefix=".card-", suffix=".tmp", dir=str(d))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(html)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return str(target)
