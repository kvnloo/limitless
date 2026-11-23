"""The synthetic app candidates example in docs/app-candidates.md: python3 -I scripts/app_candidates_example.py

A made-up week: a phone ActivityWatch DB (the AW schema) and a desktop export file in a temporary state dir,
holding well-known public app ids and made-up app names only. Nothing outside the temporary dir is read or
written; nothing is sent.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import app_candidates, aw_desktop, doctor, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 1894708800.0
M, H, D = 60.0, 3600.0, 86400.0
NS = 1_000_000_000
SCHEMA = """
CREATE TABLE buckets (id INTEGER PRIMARY KEY, name TEXT, type TEXT, client TEXT, hostname TEXT,
                      created TEXT, datastr TEXT);
CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, bucketrow INTEGER, starttime INTEGER,
                     endtime INTEGER, data TEXT);
"""
PHONE = [   # (start offset from the week's end, minutes, app, package)
    (-5 * D, 75, "Instagram", "com.instagram.android"),
    (-4 * D, 40, "TikTok", "com.zhiliaoapp.musically"),
    (-3 * D, 50, "Instagram", "com.instagram.android"),
    (-2 * D, 25, "Reddit", "com.reddit.frontpage"),
    (-2 * D + 2 * H, 30, "Notely", "org.example.notely"),
]
DESKTOP = [  # (start offset, minutes, app)
    (-4 * D, 180, "Code"),
    (-3 * D, 60, "Alacritty"),
    (-2 * D, 150, "firefox"),
    (-6 * H, 200, "Code"),
]


def phone_db(path, end):
    Path(path).unlink(missing_ok=True)
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    con.execute("INSERT INTO buckets VALUES (1, 'w', 'currentwindow', 'example', 'phone', '', '{}')")
    for off, minutes, app, pkg in PHONE:
        s = end + off
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (1, ?, ?, ?)",
                    (int(s * NS), int((s + minutes * M) * NS), json.dumps({"app": app, "package": pkg})))
    con.commit()
    con.close()


def _ev(s, e, **data):
    return {"timestamp": datetime.fromtimestamp(s, timezone.utc).isoformat(), "duration": e - s, "data": data}


def desktop_export(path, end):
    wins = [(end + off, end + off + minutes * M, app) for off, minutes, app in DESKTOP]
    b = {"aw-watcher-window_desk": {"id": "aw-watcher-window_desk", "type": "currentwindow",
                                    "events": [_ev(s, e, app=a, title="a synthetic title") for s, e, a in wins]},
         "aw-watcher-afk_desk": {"id": "aw-watcher-afk_desk", "type": "afkstatus",
                                 "events": [_ev(end - 7 * D, end, status="not-afk")]}}
    Path(path).write_text(json.dumps({"buckets": b}))


def show(title, out):
    print(f"## {title}")
    print(out if isinstance(out, str) else json.dumps(out, sort_keys=True))


def setup(st: Path, end: float, **cfg) -> dict:
    phone_db(st / "aw.db", end)
    desktop_export(st / "desk.json", end)
    path = st / "config.json"
    path.write_text(json.dumps(dict({"state": str(st), "aw_db": "aw.db", "desktop_aw_export": "desk.json"}, **cfg)))
    return {"LIMITLESS_CONFIG": str(path), "LIMITLESS_STATE": str(st)}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        st = Path(tmp)
        reader = StateReader(st)
        env = setup(st, NOW)
        show("reply_line", app_candidates.reply_line(app_candidates.read_for(reader, NOW, env)))
        env = setup(st, NOW, feed_apps=["Snapchat"], app_candidates_max=2)
        show("reply_line, feed_apps already set to Snapchat, app_candidates_max two",
             app_candidates.reply_line(app_candidates.read_for(reader, NOW, env)))
        env = setup(st, NOW)
        show("limitless_app_candidates (no raw opt-in)", tools.app_candidates(reader, NOW, env=env))
        raw = tools.app_candidates(reader, NOW, raw=True, env=env)["value"]
        show("limitless_app_candidates value (raw opt-in)", raw)
        empty = {"LIMITLESS_CONFIG": str(st / "none.json"), "LIMITLESS_STATE": str(st)}
        show("limitless_app_candidates, no ActivityWatch source", tools.app_candidates(reader, NOW, env=empty))
        aw_desktop._HOLD.clear()
        print("## doctor rows")
        for e in (env, empty):
            with mock.patch.dict(os.environ, e, clear=True):
                print(doctor.text([doctor.tool_row("limitless_app_candidates", NOW)]))
        env = setup(st, time.time())   # the CLI reads the real clock: the same week, ending now
        cli = [sys.executable, "-I", str(ROOT / "bin" / "limitless-app-candidates")]
        keep = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")}
        r = subprocess.run(cli, env=dict(keep, **env), capture_output=True, text=True, timeout=60)
        show("bin/limitless-app-candidates", r.stdout.rstrip("\n"))
        r = subprocess.run(cli, env=dict(keep, **empty), capture_output=True, text=True, timeout=60)
        show("bin/limitless-app-candidates, no source (stderr)", r.stderr.rstrip("\n"))


if __name__ == "__main__":
    main()
