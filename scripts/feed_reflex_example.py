"""The synthetic feed reflex example in docs/feed-reflex.md: python3 -I scripts/feed_reflex_example.py

Made-up unlocks and app rows in a temporary ActivityWatch-shaped DB (made-up app names); reads no real state,
writes nothing else, sends nothing. UTC stands in for the local zone.
"""
import json
import os
import sqlite3
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from limitless import doctor, feed_reflex, habit_catalogue, jobs_runner, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

UTC = timezone.utc
TODAY = date(2030, 1, 28)
NOW = datetime.combine(TODAY, time(21), UTC).timestamp()
NS = 1_000_000_000
SCHEMA = """
CREATE TABLE buckets(id INTEGER PRIMARY KEY, name TEXT UNIQUE, type TEXT, client TEXT, hostname TEXT,
                     created TEXT, data TEXT);
CREATE TABLE events(id INTEGER PRIMARY KEY, bucketrow INTEGER REFERENCES buckets(id), starttime INTEGER,
                    endtime INTEGER, data TEXT);
"""


def make_db(path, unlocks, spans):
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    con.execute("INSERT INTO buckets VALUES (1, 'unlocks', 'os.lockscreen.unlocks', 'synthetic', 'synthetic', '', '{}')")
    con.execute("INSERT INTO buckets VALUES (2, 'window', 'currentwindow', 'synthetic', 'synthetic', '', '{}')")
    for t in unlocks:
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (1, ?, ?, '{}')",
                    (int(t * NS), int(t * NS)))
    for s, e, app in spans:
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (2, ?, ?, ?)",
                    (int(s * NS), int(e * NS), json.dumps({"app": app, "package": "org.example." + app})))
    con.commit()
    con.close()


def week(feed_first_every):
    """Two unlocks a day for the six days before NOW. After each, the first app within a few seconds is the
    made-up feed app on every ``feed_first_every``-th unlock, else a notes app; one unlock a day opens the feed
    only after the gap, and one opens notes first, then the feed."""
    unlocks, spans = [], []
    for d in range(6):
        for k, hour in enumerate((9, 15)):
            u = datetime.combine(TODAY - timedelta(days=d), time(hour), UTC).timestamp()
            unlocks.append(u)
            i = len(unlocks)
            if i % feed_first_every == 0:
                spans.append((u + 3, u + 400, "feedapp"))
            elif k == 0:
                spans.append((u + 300, u + 600, "feedapp"))           # after the gap: does not count
            else:
                spans += [(u + 2, u + 20, "notes"), (u + 21, u + 500, "feedapp")]   # notes first: does not count
    return unlocks, spans


def show(title, out):
    print(f"## {title}")
    print(json.dumps(out, sort_keys=True))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        st = Path(tmp)
        cfg_path = st / "config.json"
        env = {"LIMITLESS_CONFIG": str(cfg_path)}
        reader = StateReader(st)
        habit = {"week_of": (TODAY - timedelta(days=6)).isoformat(), "habit": "Synthetic habit"}

        def run(title, db, raw=False, **cfg):
            cfg_path.write_text(json.dumps(dict({"aw_db": db} if db else {}, **cfg)))
            show(title, tools.feed_reflex(reader, NOW, raw=raw, env=env, tz=UTC))

        make_db(st / "often.db", *week(2))
        make_db(st / "rarely.db", *week(12))
        make_db(st / "few.db", *[x[:3] for x in week(1)])
        run("no feed_apps set", "often.db")
        run("feed_apps set, no aw_db", None, feed_apps=["feedapp"])
        run("too few unlocks", "few.db", feed_apps=["feedapp"])
        run("a feed first on every other unlock", "often.db", feed_apps=["feedapp"])
        run("the same, with the raw opt-in", "often.db", raw=True, feed_apps=["feedapp"])
        run("a feed first on one unlock in twelve", "rarely.db", feed_apps=["feedapp"])
        run("a wider gap (feed_reflex_gap_s: a duration)", "rarely.db", feed_apps=["feedapp"],
            feed_reflex_gap_s=600)

        cfg_path.write_text(json.dumps({"aw_db": "often.db", "feed_apps": ["feedapp"]}))
        print("## week review line")
        print(jobs_runner.week_feed_reflex(st, habit, env, st, UTC))
        print("## Next up after a Drop, the reflex often")
        print(jobs_runner.week_next(st, habit, "Drop", env, st, tz=UTC))
        cfg_path.write_text(json.dumps({"aw_db": "often.db"}))
        print("## Next up after a Drop, no feed_apps")
        print(jobs_runner.week_next(st, habit, "Drop", env, st, tz=UTC))
        print("## doctor rows")
        for cfg in ({}, {"feed_apps": ["feedapp"]}, {"feed_apps": ["feedapp"], "aw_db": "few.db"},
                    {"feed_apps": ["feedapp"], "aw_db": "often.db"}):
            print(doctor.text([doctor.feed_reflex_row(dict(cfg, state=str(st)), NOW)]))
        print("## circuit breaker entry")
        print(json.dumps(dict(habit_catalogue.CIRCUIT_BREAKER), sort_keys=True))


if __name__ == "__main__":
    os.environ.pop("LIMITLESS_FEED_APPS", None)
    os.environ.pop("LIMITLESS_AW_DB", None)
    main()
