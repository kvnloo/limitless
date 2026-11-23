"""Propose the work-app and feed-app lists from observed app time, as one reply the person can send back.

    c = candidates(rows, known=KNOWN, work_apps=(), feed_apps=(), max_n=MAX_N, lo=None, hi=None)
        -> {"work": [entry], "feed": [entry], "other": [entry], "total_s", "newest", "why"}
        entry = {"name", "seconds", "kept", "names"}
    text = reply_line(c)     # "work apps: A, B" and "feed apps: C, D" (two lines at most), "" when unknown
    word = label(c)          # the T1 words: "work and feed app lists proposed", or "unknown: <why>"

``rows`` are app-in-foreground rows in blocks.read_rows / aw_desktop.rows shape (``start``, ``end`` epoch
seconds and ``names``, a list, or ``app`` / ``package``), phone and desktop alike; ``lo`` / ``hi`` cut them
to a window (read_for passes the last LOOKBACK_DAYS days). Each app's foreground time is summed per app:
names are trimmed and case-folded, and the names one row carries together (a display name and its package
id) are one app, as are the aliases of one KNOWN app. An app is named by the name that covers the most of
its time (a display name before a package id on a tie), so the name matches the rows when it is put in
config. A name with a comma, a line break or the ``title:`` prefix would not survive the reply, so it is
left out.

The split uses KNOWN, a small public map of well-known app ids and names: feeds (Instagram, TikTok, X or
Twitter, Reddit, YouTube, Facebook, Snapchat, Threads and their Android package ids) and work apps (code
editors, terminals, GitHub). Browsers are ambiguous and stay ``other``, never work by default; an app the
map does not know is ``other``. The apps already in config (``flow_work_apps``, ``feed_apps``) are marked
kept and are never dropped: they stay in their own list, with their own spelling, even when not seen; the
config beats the map. Each list then takes up to ``max_n`` new apps by time (config ``app_candidates_max``,
default MAX_N). ``other`` is the top ``max_n`` apps the map does not place, for the raw view only.

Unknown is never empty lists: no rows, less than MIN_TOTAL_S of app time, or no work or feed app at all is
``work`` / ``feed`` None with a plain, digit-free ``why``. App names are the person's own data: they appear
only in reply_line's text and the tool's raw opt-in value, never in the label, a doctor reason or a log.

It only suggests: nothing here writes config or any file, and nothing is sent; the person replies. A proxy:
an app in the foreground is not work or a feed read. Durations only, never a clock time. Stdlib only,
Python 3.9+.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional

LOOKBACK_DAYS = 7
MAX_N, MAX_CONFIG = 5, "app_candidates_max"
MIN_TOTAL_S = 30 * 60.0          # less app time than this over the window: too little to propose lists
MODALITY = "proxy"               # an app in the foreground is not work or a feed read
WORK, FEED, OTHER = "work", "feed", "other"
TITLE = "title:"

NO_ROWS = "no app activity rows"
TOO_LITTLE = "too little app activity to propose lists"
NO_KNOWN = "no well-known work or feed app seen"
REASONS = (NO_ROWS, TOO_LITTLE, NO_KNOWN)

BOTH = "work and feed app lists proposed"
WORK_ONLY = "work app list proposed"
FEED_ONLY = "feed app list proposed"
WORDS = (BOTH, WORK_ONLY, FEED_ONLY)
UNKNOWN_PREFIX = "unknown: "


# Public, well-known app ids and names only; the first alias of a group is its own, the rest join it.
_GROUPS = (
    (FEED, ("instagram", "com.instagram.android")),
    (FEED, ("tiktok", "com.zhiliaoapp.musically", "com.ss.android.ugc.trill")),
    (FEED, ("x", "twitter", "com.twitter.android")),
    (FEED, ("reddit", "com.reddit.frontpage")),
    (FEED, ("youtube", "com.google.android.youtube")),
    (FEED, ("facebook", "com.facebook.katana", "com.facebook.lite")),
    (FEED, ("snapchat", "com.snapchat.android")),
    (FEED, ("threads", "com.instagram.barcelona")),
    (WORK, ("code", "visual studio code", "vscode", "code.exe", "code - oss", "codium", "vscodium")),
    (WORK, ("cursor",)),
    (WORK, ("zed",)),
    (WORK, ("sublime_text", "sublime text")),
    (WORK, ("pycharm", "jetbrains-pycharm", "pycharm64.exe")),
    (WORK, ("intellij idea", "jetbrains-idea", "idea64.exe")),
    (WORK, ("android studio", "jetbrains-studio", "studio64.exe")),
    (WORK, ("emacs",)),
    (WORK, ("vim", "gvim", "nvim", "neovim")),
    (WORK, ("terminal", "com.apple.terminal")),
    (WORK, ("iterm2", "iterm")),
    (WORK, ("gnome-terminal", "gnome-terminal-server")),
    (WORK, ("konsole",)),
    (WORK, ("alacritty",)),
    (WORK, ("kitty",)),
    (WORK, ("wezterm", "wezterm-gui")),
    (WORK, ("windows terminal", "windowsterminal.exe")),
    (WORK, ("xterm",)),
    (WORK, ("termux", "com.termux")),
    (WORK, ("github desktop", "github", "com.github.android")),
    # browsers: work or feed depends on the tab, so never work by default
    (OTHER, ("firefox", "org.mozilla.firefox", "firefox.exe")),
    (OTHER, ("chrome", "google-chrome", "google chrome", "chrome.exe", "com.android.chrome")),
    (OTHER, ("chromium", "chromium-browser")),
    (OTHER, ("safari", "com.apple.safari")),
    (OTHER, ("brave", "brave-browser", "com.brave.browser")),
    (OTHER, ("microsoft edge", "msedge", "msedge.exe", "com.microsoft.emmx")),
    (OTHER, ("samsung internet", "com.sec.android.app.sbrowser")),
)
KNOWN = {a: kind for kind, aliases in _GROUPS for a in aliases}
_ALIAS_OF = {a: aliases[0] for _, aliases in _GROUPS for a in aliases}


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _ok(name: str) -> bool:
    return bool(name) and not any(c in name for c in ",\n\r\t") and not name.startswith(TITLE)


def _names(r: Mapping) -> set:
    raw = r.get("names") if isinstance(r.get("names"), (list, tuple, set)) else (r.get("app"), r.get("package"))
    return {v.strip().casefold() for v in raw if isinstance(v, str)} - {""}


def _clean(items) -> list:
    if isinstance(items, str):
        items = items.split(",")
    out = []
    for v in items if isinstance(items, (list, tuple)) else ():
        w = v.strip() if isinstance(v, str) else ""
        if w and w.casefold() not in [o.casefold() for o in out]:
            out.append(w)
    return out


class _Sets:
    def __init__(self):
        self.up = {}

    def find(self, a):
        self.up.setdefault(a, a)
        while self.up[a] != a:
            self.up[a] = self.up[self.up[a]]
            a = self.up[a]
        return a

    def join(self, a, b):
        self.up[self.find(a)] = self.find(b)


def _spans(rows, lo, hi) -> list:
    out = []
    for r in rows or ():
        if not isinstance(r, Mapping):
            continue
        s, e = _num(r.get("start")), _num(r.get("end"))
        if s is None or e is None:
            continue
        if lo is not None:
            s = max(s, lo)
        if hi is not None:
            e = min(e, hi)
        names = {n for n in _names(r) if _ok(n)}
        if e > s and names:
            out.append((s, e, names))
    return out


def _unknown(why: str, total_s: float = 0.0, newest=None) -> dict:
    return {"work": None, "feed": None, "other": None, "total_s": total_s, "newest": newest, "why": why}


def _pick(per_name: Mapping, group: Iterable) -> str:
    # most time first; a display name (no dot) before a package id; then the shorter, then a-z
    return min(group, key=lambda n: (-per_name.get(n, 0.0), "." in n, len(n), n))


def _kind(group: Iterable, known: Mapping) -> str:
    kinds = {known.get(n) for n in group} - {None}
    for k in (FEED, WORK, OTHER):
        if k in kinds:
            return k
    return OTHER


def candidates(rows, known: Mapping = KNOWN, *, work_apps: Iterable = (), feed_apps: Iterable = (),
               max_n: int = MAX_N, lo: Optional[float] = None, hi: Optional[float] = None,
               min_total_s: float = MIN_TOTAL_S) -> dict:
    """The proposed lists from ``rows``: per-app foreground time split into work, feed and other with
    ``known``; config apps (``work_apps``, ``feed_apps``) kept; up to ``max_n`` new apps per list. Unknown
    (lists None, ``why`` set) with no rows, too little time or no work or feed app. Pure."""
    n = max_n if isinstance(max_n, int) and not isinstance(max_n, bool) and max_n > 0 else MAX_N
    spans = _spans(rows, lo, hi)
    if not spans:
        return _unknown(NO_ROWS)
    sets, per_name = _Sets(), {}
    for s, e, names in spans:
        first = next(iter(names))
        for a in names:
            sets.join(a, first)
            per_name[a] = per_name.get(a, 0.0) + (e - s)
            if a in _ALIAS_OF and isinstance(known, Mapping) and a in known:
                sets.join(a, "\0" + _ALIAS_OF[a])
    groups, secs = {}, {}
    for a in per_name:
        groups.setdefault(sets.find(a), set()).add(a)
    for s, e, names in spans:   # an app's time: each row once, whatever names it carries
        root = sets.find(next(iter(names)))
        secs[root] = secs.get(root, 0.0) + (e - s)
    total = sum(e - s for s, e, _ in spans)
    newest = max(e for _, e, _ in spans)
    if total < (min_total_s if _num(min_total_s) is not None else MIN_TOTAL_S):
        return _unknown(TOO_LITTLE, total, newest)
    keep = {WORK: _clean(work_apps), FEED: _clean(feed_apps)}
    keep[FEED] = [k for k in keep[FEED] if k.casefold() not in {w.casefold() for w in keep[WORK]}]
    out = {WORK: [], FEED: [], OTHER: []}
    seen_kept = set()
    known = known if isinstance(known, Mapping) else {}
    for root, g in groups.items():
        entry = {"name": _pick(per_name, g), "seconds": secs[root], "kept": False, "names": sorted(g)}
        for k in (WORK, FEED):
            hit = [w for w in keep[k] if w.casefold() in g]
            if hit:
                entry.update(name=hit[0], kept=True)
                seen_kept.update(w.casefold() for w in hit)
                out[k].append(entry)
                break
        else:
            out[_kind(g, known)].append(entry)
    for k in out:
        out[k].sort(key=lambda x: (-x["seconds"], not x["kept"], x["name"]))
        new = 0
        top = []
        for x in out[k]:
            if x["kept"]:
                top.append(x)
            elif new < n:
                top.append(x)
                new += 1
        out[k] = top
    for k in (WORK, FEED):
        out[k] += [{"name": w, "seconds": 0.0, "kept": True, "names": []}
                   for w in keep[k] if w.casefold() not in seen_kept]
    if not out[WORK] and not out[FEED]:
        return _unknown(NO_KNOWN, total, newest)
    return dict(out, total_s=total, newest=newest, why="")


def label(c: Optional[Mapping]) -> str:
    """The T1 words: which lists are proposed, or "unknown: <why>". Digit-free; never an app name."""
    if not isinstance(c, Mapping) or c.get("work") is None or c.get("feed") is None:
        why = c.get("why") if isinstance(c, Mapping) else None
        return UNKNOWN_PREFIX + (why if why in REASONS else NO_ROWS)
    if c["work"] and c["feed"]:
        return BOTH
    return WORK_ONLY if c["work"] else FEED_ONLY


def reply_line(c: Optional[Mapping]) -> str:
    """The reply the person can send back as is: ``work apps: A, B`` and ``feed apps: C, D``, one line per
    list that has an app (two lines at most); "" when unknown."""
    if label(c) not in WORDS:
        return ""
    lines = [f"{k} apps: " + ", ".join(e["name"] for e in c[k]) for k in (WORK, FEED) if c[k]]
    return "\n".join(lines)
