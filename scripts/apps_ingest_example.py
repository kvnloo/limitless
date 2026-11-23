"""The synthetic apps ingest example in docs/apps-ingest.md: python3 -I scripts/apps_ingest_example.py

A temporary Hermes-shaped session DB with made-up messages and made-up app names; a temporary state dir and
config. Reads no real state, sends nothing. The same lines bin/limitless-apps-ingest prints, at a fixed time.
"""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from limitless import apps_reply, doctor, habit_replies  # noqa: E402

NOW = 1_900_000_000.0


def make_db(path, messages):
    con = sqlite3.connect(str(path))
    con.executescript("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at REAL NOT NULL);"
                      "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,"
                      " role TEXT NOT NULL, content TEXT, timestamp REAL NOT NULL);")
    con.execute("INSERT INTO sessions VALUES ('s1', 'telegram', ?)", (NOW - 7200,))
    for role, text, t in messages:
        con.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES ('s1', ?, ?, ?)",
                    (role, text, t))
    con.commit()
    con.close()


def run(st, db, now, write):
    print(f"$ limitless-apps-ingest{' --write' if write else ''}")
    replies = habit_replies.replies_from_hermes_db(db, apps_reply.read_after(st, now))
    for line in apps_reply.lines(apps_reply.ingest(st, replies, now, dry_run=not write), write):
        print(line)


def main():
    with tempfile.TemporaryDirectory() as d:
        home = Path(d)
        st = home / "state"
        st.mkdir()
        db = home / "state.db"
        make_db(db, [("user", "thanks, sounds good", NOW - 900),
                     ("user", "Work apps: editorapp, termapp, notesapp\nfeed apps: scrollapp, clipapp", NOW - 600),
                     ("assistant", "work apps: not-from-the-person", NOW - 590),
                     ("user", "feed apps: scrollapp", NOW - 300)])
        cfg = {"state": str(st)}
        print("## doctor row before any reply")
        print(doctor.text([doctor.apps_row(cfg, env={})]))
        print("## a dry run, then --write")
        run(st, db, NOW, False)
        run(st, db, NOW, True)
        print(f"## {apps_reply.APPS_FILE} (mode {oct((st / apps_reply.APPS_FILE).stat().st_mode & 0o777)[2:]})")
        print(json.dumps(apps_reply.load(st)))
        print(doctor.text([doctor.apps_row(cfg, env={})]))
        print("## a second run reads only newer messages")
        run(st, db, NOW + 60, True)
        print("## work apps: none clears the work list")
        make_db(home / "later.db", [("user", "work apps: none", NOW + 120), ("user", "work apps please", NOW + 130)])
        run(st, home / "later.db", NOW + 180, True)
        print(json.dumps(apps_reply.load(st)))
        print(doctor.text([doctor.apps_row(cfg, env={})]))
        print("## config wins over the reply")
        print(doctor.text([doctor.apps_row(dict(cfg, feed_apps=["cfgfeedapp"]), env={})]))
        print(apps_reply.list_for(apps_reply.FEED, dict(cfg, feed_apps=["cfgfeedapp"]), st, env={}))


if __name__ == "__main__":
    main()
