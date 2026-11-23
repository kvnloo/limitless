"""Apps ingest: the newest work apps / feed apps reply from the Hermes session DB into apps.json.

Dry run unless written. Synthetic data only; nothing sends.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import apps_reply  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-apps-ingest"
NOW = 2_000_000_000.0
W, F = apps_reply.WORK, apps_reply.FEED


def run(st, replies, dry_run=True, now=NOW):
    return apps_reply.ingest(st, replies, now, dry_run=dry_run)


class Ingest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)
        self.file = self.st / apps_reply.APPS_FILE

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_reply_is_one_nothing_row(self):
        got = run(self.st, [])
        self.assertEqual([r["action"] for r in got["rows"]], [apps_reply.NOTHING])
        self.assertIsNone(got["apps"])
        self.assertFalse(self.file.exists())

    def test_dry_run_says_what_it_would_write_and_writes_nothing(self):
        got = run(self.st, [(NOW - 60, "work apps: editor, terminal")])
        self.assertEqual(got["rows"][0]["action"], apps_reply.WOULD_WRITE)
        self.assertEqual(got["apps"], {"since": apps_reply.iso(NOW - 60), W: ["editor", "terminal"], F: []})
        self.assertFalse(self.file.exists())

    def test_write_writes_apps_json_mode_0600(self):
        run(self.st, [(NOW - 60, "work apps: editor\nfeed apps: scrollerapp")], dry_run=False)
        self.assertEqual(apps_reply.load(self.st),
                         {"since": apps_reply.iso(NOW - 60), W: ["editor"], F: ["scrollerapp"]})
        self.assertEqual(oct(self.file.stat().st_mode & 0o777), "0o600")
        self.assertEqual([p.name for p in self.st.iterdir()], [apps_reply.APPS_FILE], "no temp file left")

    def test_newest_message_wins_per_list(self):
        got = run(self.st, [(NOW - 300, "work apps: old-editor\nfeed apps: scrollerapp"),
                            (NOW - 200, "thanks"), (NOW - 100, "work apps: editor")], dry_run=False)
        self.assertEqual([r["action"] for r in got["rows"]],
                         [apps_reply.WRITE, apps_reply.IGNORE, apps_reply.WRITE])
        self.assertEqual(apps_reply.load(self.st), {"since": apps_reply.iso(NOW - 100), W: ["editor"],
                                                    F: ["scrollerapp"]})

    def test_a_fully_replaced_reply_is_ignored(self):
        got = run(self.st, [(NOW - 300, "work apps: a"), (NOW - 100, "work apps: b")])
        self.assertEqual([r["action"] for r in got["rows"]], [apps_reply.IGNORE, apps_reply.WOULD_WRITE])

    def test_a_reply_keeps_the_other_list_already_in_apps_json(self):
        run(self.st, [(NOW - 300, "feed apps: scrollerapp")], dry_run=False)
        run(self.st, [(NOW - 100, "work apps: editor")], dry_run=False)
        self.assertEqual(apps_reply.load(self.st)[F], ["scrollerapp"])
        self.assertEqual(apps_reply.load(self.st)[W], ["editor"])

    def test_none_clears(self):
        run(self.st, [(NOW - 300, "work apps: editor")], dry_run=False)
        run(self.st, [(NOW - 100, "work apps: none")], dry_run=False)
        self.assertEqual(apps_reply.load(self.st)[W], [])

    def test_noise_writes_nothing(self):
        got = run(self.st, [(NOW - 60, "my work apps are editor"), (NOW - 30, "feed apps")], dry_run=False)
        self.assertEqual({r["action"] for r in got["rows"]}, {apps_reply.IGNORE})
        self.assertFalse(self.file.exists())

    def test_a_reply_at_or_before_the_current_since_is_ignored(self):
        run(self.st, [(NOW - 100, "work apps: editor")], dry_run=False)
        got = run(self.st, [(NOW - 100, "work apps: x"), (NOW - 500, "work apps: y")], dry_run=False)
        self.assertEqual({r["action"] for r in got["rows"]}, {apps_reply.IGNORE})
        self.assertEqual(apps_reply.load(self.st)[W], ["editor"])

    def test_a_reply_after_now_is_ignored(self):
        got = run(self.st, [(NOW + 60, "work apps: editor")], dry_run=False)
        self.assertEqual(got["rows"][0]["action"], apps_reply.IGNORE)
        self.assertFalse(self.file.exists())

    def test_read_after(self):
        self.assertEqual(apps_reply.read_after(self.st, NOW), NOW - apps_reply.FIRST_READ_S)
        run(self.st, [(NOW - 100.4, "work apps: editor")], dry_run=False)
        self.assertEqual(apps_reply.read_after(self.st, NOW), NOW - 101 + 1)

    def test_rows_never_echo_a_reply_or_a_name(self):
        got = run(self.st, [(NOW - 60, "synthetic-private-words"), (NOW - 30, "work apps: synthetic-app-name")])
        self.assertNotIn("synthetic-private-words", json.dumps(got["rows"]))
        self.assertNotIn("synthetic-app-name", json.dumps(got["rows"]))

    def test_load_is_none_for_a_missing_or_broken_file(self):
        self.assertIsNone(apps_reply.load(self.st))
        self.file.write_text("[1]")
        self.assertIsNone(apps_reply.load(self.st))


class IngestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        self.cfg = self.home / "config.json"
        now = time.time()
        self.db = self.home / "hermes.db"
        con = sqlite3.connect(str(self.db))
        con.executescript("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at REAL NOT NULL);"
                          "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,"
                          " role TEXT NOT NULL, content TEXT, timestamp REAL NOT NULL);")
        con.execute("INSERT INTO sessions VALUES ('s1', 'telegram', ?)", (now - 7200,))
        for role, text, t in (("user", "synthetic-private-words", now - 900),
                              ("user", "Work apps: editor, terminal\nfeed apps: scrollerapp", now - 600),
                              ("assistant", "work apps: not-from-the-person", now - 590)):
            con.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES ('s1', ?, ?, ?)",
                        (role, text, t))
        con.commit()
        con.close()
        self.reply_at = now - 600
        self.env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", ""), "LIMITLESS_STATE": str(self.st),
                    "LIMITLESS_CONFIG": str(self.cfg)}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, **env):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=dict(self.env, **env),
                              capture_output=True, text=True, timeout=60)

    def test_no_db_configured_does_nothing_and_says_so(self):
        r = self.run_cli("--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no Hermes DB", r.stdout)
        self.assertFalse((self.st / apps_reply.APPS_FILE).exists())

    def test_dry_run_by_default_prints_what_it_would_write(self):
        r = self.run_cli("--db", str(self.db))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would write: work apps, feed apps", r.stdout)
        self.assertIn('"work_apps": ["editor", "terminal"]', r.stdout)
        self.assertIn("dry run", r.stdout)
        self.assertNotIn("synthetic-private-words", r.stdout)
        self.assertNotIn("not-from-the-person", r.stdout)
        self.assertFalse((self.st / apps_reply.APPS_FILE).exists())

    def test_write_writes_apps_json_and_never_the_config(self):
        self.cfg.write_text('{"flow_work_apps": ["cfg-editor"]}')
        before = self.cfg.read_bytes()
        r = self.run_cli("--db", str(self.db), "--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("write: work apps, feed apps", r.stdout)
        self.assertEqual(apps_reply.load(self.st), {"since": apps_reply.iso(self.reply_at),
                                                    W: ["editor", "terminal"], F: ["scrollerapp"]})
        self.assertEqual(oct((self.st / apps_reply.APPS_FILE).stat().st_mode & 0o777), "0o600")
        self.assertEqual(self.cfg.read_bytes(), before)

    def test_a_second_run_reads_only_newer_replies(self):
        self.run_cli("--db", str(self.db), "--write")
        r = self.run_cli("--db", str(self.db), "--write")
        self.assertIn("nothing", r.stdout)
        self.assertEqual(apps_reply.load(self.st)[W], ["editor", "terminal"])

    def test_db_from_the_env(self):
        r = self.run_cli(LIMITLESS_HERMES_DB=str(self.db))
        self.assertIn("would write: work apps, feed apps", r.stdout)


if __name__ == "__main__":
    unittest.main()
