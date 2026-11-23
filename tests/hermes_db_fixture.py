"""A synthetic Hermes session DB (the schema habit_replies reads): sessions and messages, nothing real.

    make_db(path, [(role, text, t), ...], started=t0, source="telegram")

Shared by the apps ingest CLI tests and the apps ingest job tests. Synthetic text only.
"""
import sqlite3

SCHEMA = ("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at REAL NOT NULL);"
          "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,"
          " role TEXT NOT NULL, content TEXT, timestamp REAL NOT NULL);")


def make_db(path, messages, started, source="telegram"):
    """Write a session DB at ``path`` with one ``source`` session holding ``messages`` (role, text, t)."""
    con = sqlite3.connect(str(path))
    try:
        con.executescript(SCHEMA)
        con.execute("INSERT INTO sessions VALUES ('s1', ?, ?)", (source, started))
        for role, text, t in messages:
            con.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES ('s1', ?, ?, ?)",
                        (role, text, t))
        con.commit()
    finally:
        con.close()
    return path
