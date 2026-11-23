"""The synthetic app-lists ask example in docs/apps-ask.md: python3 -I scripts/apps_ask_example.py

A made-up week: a phone ActivityWatch DB (the AW schema) in a temporary state dir, holding well-known public
app ids only, and a temporary config and tier audit log. It shows the lines the wake brief would carry, the
mark a delivery writes, the doctor row and the seven-day rule at fixed times. Nothing outside the temporary
dir is read or written; nothing is sent (the "delivery" is a call to the told hook, as the sender makes it).
"""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import apps_ask, apps_reply, brief_post, doctor, jobs_runner  # noqa: E402

NOW = 1894708800.0
M, H, D = 60.0, 3600.0, 86400.0
NS = 1_000_000_000
SCHEMA = """
CREATE TABLE buckets (id INTEGER PRIMARY KEY, name TEXT, type TEXT, client TEXT, hostname TEXT,
                      created TEXT, datastr TEXT);
CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, bucketrow INTEGER, starttime INTEGER,
                     endtime INTEGER, data TEXT);
"""
PHONE = [   # (start offset before now, minutes, app, package)
    (5 * D, 60, "Termux", "com.termux"),
    (4 * D, 75, "Instagram", "com.instagram.android"),
    (3 * D, 30, "Reddit", "com.reddit.frontpage"),
    (2 * D, 45, "Termux", "com.termux"),
    (2 * D - 2 * H, 40, "Notely", "org.example.notely"),
]


def phone_db(path, now):
    Path(path).unlink(missing_ok=True)
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    con.execute("INSERT INTO buckets VALUES (1, 'w', 'currentwindow', 'example', 'phone', '', '{}')")
    for off, minutes, app, pkg in PHONE:
        s = now - off
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (1, ?, ?, ?)",
                    (int(s * NS), int((s + minutes * M) * NS), json.dumps({"app": app, "package": pkg})))
    con.commit()
    con.close()


def main():
    with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {}, clear=True):
        home = Path(d)
        st = home / "state"
        st.mkdir()
        cfg_path = home / "config.json"
        audit = home / "audit.jsonl"
        env = {"LIMITLESS_CONFIG": str(cfg_path), "LIMITLESS_STATE": str(st), "LIMITLESS_AUDIT": str(audit)}

        def config(**extra):
            cfg = dict({"state": str(st), "aw_db": "aw.db"}, **extra)
            cfg_path.write_text(json.dumps(cfg))
            return cfg

        def row(cfg, now):
            print(doctor.text([doctor.apps_ask_row(cfg, now, env)]))

        def brief(now):
            ask = jobs_runner.brief_apps_ask(st, now, env, home)
            print(brief_post.finalize("State: synthetic", None, now, apps_ask=ask))
            return ask

        cfg = config()
        phone_db(st / "aw.db", NOW)
        print("## both lists unset: the doctor row, then the brief")
        row(cfg, NOW)
        ask = brief(NOW)
        print(f"## {apps_ask.MARK_FILE} before any delivery: {'present' if (st / apps_ask.MARK_FILE).exists() else 'absent'}")
        print("## the brief went out (a real delivery): the sender marks it told")
        if ask:
            jobs_runner.brief_apps_ask_told(st, NOW, env, home)
        mark = st / apps_ask.MARK_FILE
        print(f"{apps_ask.MARK_FILE} (mode {oct(mark.stat().st_mode & 0o777)[2:]}) keys: {sorted(json.loads(mark.read_text()))}")
        row(cfg, NOW + 5 * D)
        print("## five days later")
        brief(NOW + 5 * D)
        print("## eight days later, still unset (a fresh week of app time)")
        phone_db(st / "aw.db", NOW + 8 * D)
        row(cfg, NOW + 8 * D)
        brief(NOW + 8 * D)
        print("## the person replied: a list is set")
        apps_reply.ingest(st, [(NOW + 8 * D + 60, ask.splitlines()[1])], NOW + 8 * D + 120, dry_run=False)
        row(cfg, NOW + 9 * D)
        brief(NOW + 9 * D)
        print("## config apps_ask off")
        row(config(apps_ask="off"), NOW + 9 * D)
        print("## the tier audit rows: counts and a hash, never a name")
        for line in audit.read_text().splitlines():
            r = json.loads(line)
            print(f"hook={r['hook']} lines={r['lines']} digits={r['digits']} blocked={r['blocked']}")


if __name__ == "__main__":
    main()
