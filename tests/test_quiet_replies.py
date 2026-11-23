"""Quiet replies: quiet / quiet tonight / snooze / on, read from the Hermes session DB into quiet.json.

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

from limitless import quiet  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-quiet-ingest"
NOW = 2_000_000_000.0


class Command(unittest.TestCase):
    def test_the_four_commands(self):
        self.assertEqual(quiet.command("quiet"), "off")
        self.assertEqual(quiet.command("quiet tonight"), "quiet_tonight")
        self.assertEqual(quiet.command("snooze"), "snoozed")
        self.assertEqual(quiet.command("on"), "on")

    def test_case_space_and_trailing_punctuation_do_not_matter(self):
        self.assertEqual(quiet.command("  Quiet  Tonight! "), "quiet_tonight")
        self.assertEqual(quiet.command("SNOOZE."), "snoozed")
        self.assertEqual(quiet.command("On"), "on")

    def test_the_long_snooze_is_the_same_snooze(self):
        self.assertEqual(quiet.command("Snooze until I write again"), "snoozed")

    def test_only_the_whole_message_counts(self):
        for text in ("quiet please", "is it quiet", "turn it on", "on my way", "snooze 2h", "quiet until 22:00",
                     "snooze for an hour", "", "   ", None, 5, "quietly"):
            self.assertIsNone(quiet.command(text), text)


def rows(replies, st, dry_run=True, now=NOW):
    return quiet.ingest(st, replies, now, dry_run=dry_run)


class Ingest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_reply_is_one_nothing_row(self):
        [r] = rows([], self.st)
        self.assertEqual(r["action"], quiet.NOTHING)
        self.assertFalse((self.st / quiet.QUIET_FILE).exists())

    def test_dry_run_says_what_it_would_write_and_writes_nothing(self):
        [r] = rows([(NOW - 60, "quiet")], self.st)
        self.assertEqual((r["action"], r["mode"]), (quiet.WOULD_WRITE, "off"))
        self.assertFalse((self.st / quiet.QUIET_FILE).exists())

    def test_write_sets_the_mode_and_since_the_reply(self):
        rows([(NOW - 60, "Snooze")], self.st, dry_run=False)
        self.assertEqual(quiet.load(self.st), {"mode": "snoozed", "since": quiet.iso(NOW - 60)})

    def test_the_latest_command_wins(self):
        out = rows([(NOW - 300, "quiet"), (NOW - 200, "thanks"), (NOW - 100, "on")], self.st, dry_run=False)
        self.assertEqual([r["action"] for r in out], [quiet.IGNORE, quiet.IGNORE, quiet.WRITE])
        self.assertEqual(quiet.load(self.st)["mode"], "on")

    def test_other_messages_write_nothing(self):
        out = rows([(NOW - 60, "quiet please"), (NOW - 30, "snooze 2h")], self.st, dry_run=False)
        self.assertEqual({r["action"] for r in out}, {quiet.IGNORE})
        self.assertFalse((self.st / quiet.QUIET_FILE).exists())

    def test_a_reply_at_or_before_the_current_since_is_ignored(self):
        quiet.write(self.st, "off", NOW - 100)
        out = rows([(NOW - 100, "on"), (NOW - 500, "on")], self.st, dry_run=False)
        self.assertEqual({r["action"] for r in out}, {quiet.IGNORE})
        self.assertEqual(quiet.load(self.st)["mode"], "off")

    def test_a_reply_after_now_is_ignored(self):
        [r] = rows([(NOW + 60, "quiet")], self.st, dry_run=False)
        self.assertEqual(r["action"], quiet.IGNORE)
        self.assertFalse((self.st / quiet.QUIET_FILE).exists())

    def test_rows_never_echo_the_reply(self):
        out = rows([(NOW - 60, "synthetic-private-words"), (NOW - 30, "quiet")], self.st)
        self.assertNotIn("synthetic-private-words", json.dumps(out))

    def test_rows_are_digit_free_but_the_reply_time(self):
        for r in rows([(NOW - 60, "hello"), (NOW - 30, "quiet tonight")], self.st):
            for k in ("mode", "action", "reason", "label"):
                self.assertFalse(any(c.isdigit() for c in str(r.get(k))), r)

    def test_read_after_is_the_second_after_the_current_since(self):
        quiet.write(self.st, "off", NOW - 100.4)      # since is kept in whole seconds
        self.assertEqual(quiet.read_after(self.st, NOW), NOW - 101 + 1)

    def test_read_after_with_no_file_looks_back_one_ingest_horizon(self):
        self.assertEqual(quiet.read_after(self.st, NOW), NOW - quiet.FIRST_READ_S)


class IngestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        now = time.time()
        self.db = self.home / "hermes.db"
        con = sqlite3.connect(str(self.db))
        con.executescript("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at REAL NOT NULL);"
                          "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,"
                          " role TEXT NOT NULL, content TEXT, timestamp REAL NOT NULL);")
        con.execute("INSERT INTO sessions VALUES ('s1', 'telegram', ?)", (now - 7200,))
        for role, text, t in (("user", "synthetic-private-words", now - 900), ("user", "Quiet tonight", now - 600),
                              ("assistant", "on", now - 590)):
            con.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES ('s1', ?, ?, ?)",
                        (role, text, t))
        con.commit()
        con.close()
        self.reply_at = now - 600
        self.env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", ""), "LIMITLESS_STATE": str(self.st),
                    "LIMITLESS_CONFIG": str(self.home / "config.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, **env):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=dict(self.env, **env),
                              capture_output=True, text=True, timeout=60)

    def test_no_db_configured_does_nothing_and_says_so(self):
        r = self.run_cli("--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no Hermes DB", r.stdout)
        self.assertFalse((self.st / quiet.QUIET_FILE).exists())

    def test_dry_run_by_default(self):
        r = self.run_cli("--db", str(self.db))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would write: quiet tonight", r.stdout)
        self.assertIn("dry run", r.stdout)
        self.assertNotIn("synthetic-private-words", r.stdout)
        self.assertFalse((self.st / quiet.QUIET_FILE).exists())

    def test_write_writes_quiet_json(self):
        r = self.run_cli("--db", str(self.db), "--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("write: quiet tonight", r.stdout)
        self.assertEqual(quiet.load(self.st), {"mode": "quiet_tonight", "since": quiet.iso(self.reply_at)})
        self.assertNotIn(".", quiet.load(self.st)["since"], "whole seconds")
        self.assertEqual(oct((self.st / quiet.QUIET_FILE).stat().st_mode & 0o777), "0o600")

    def test_a_second_run_reads_only_newer_replies(self):
        self.run_cli("--db", str(self.db), "--write")
        r = self.run_cli("--db", str(self.db), "--write")
        self.assertIn("nothing", r.stdout)
        self.assertEqual(quiet.load(self.st)["mode"], "quiet_tonight")

    def test_db_from_the_env(self):
        r = self.run_cli(LIMITLESS_HERMES_DB=str(self.db))
        self.assertIn("would write: quiet tonight", r.stdout)


if __name__ == "__main__":
    unittest.main()
