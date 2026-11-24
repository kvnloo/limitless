"""Owner drops by reply: a whole message "drop: <id>[, <id>...]" from the owner's Telegram session appends an
owner drop row for each id the ranked ledger already has. Dry run unless --write; the mark is epochs only, 0600.

Synthetic ledgers and a synthetic session DB (tests/hermes_db_fixture.py) only; nothing sends.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import ranked_ledger as rl, scorecard, tier_audit  # noqa: E402
from hermes_db_fixture import make_db  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-ranked"
NOW = 1894708800.0
A, B, C = "synthetic-item-a", "synthetic-item-b", "synthetic-item-c"
OPEN = lambda i: {"id": i, "status": "open", "by": "agent", "evidence": ""}   # noqa: E731
DROP = lambda i: {"id": i, "status": "dropped", "by": scorecard.OWNER, "evidence": "owner reply"}   # noqa: E731


def no_digit(text):
    return not tier_audit.event("cli:limitless-ranked", text, opt_in=False, now=NOW)["blocked"]


class Parse(unittest.TestCase):
    def test_the_drop_shapes(self):
        self.assertEqual(rl.parse_drop(f"drop: {A}"), (A,))
        self.assertEqual(rl.parse_drop(f"  Drop:{A} ,  {B},{A} "), (A, B))
        self.assertEqual(rl.parse_drop(f"DROP : {A}"), (A,))

    def test_anything_else_is_none(self):
        for text in (None, "", "drop", "drop:", f"drop: {A},", f"drop: {A}, , {B}", f"please drop: {A}",
                     f"drop {A}", f"drop: {A}\nthanks", f"drop: {A} {B}", f"dropped: {A}", f"drop: {A}!",
                     f"keep: {A}", f"verified: {A}", "drop: " + "x" * 81, 12):
            self.assertIsNone(rl.parse_drop(text), repr(text))


class Ingest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.st = Path(tmp.name) / "state"
        self.st.mkdir()
        self.ledger = Path(tmp.name) / "ranked.jsonl"
        self.seed(OPEN(A), OPEN(B))

    def seed(self, *rows):
        self.ledger.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def rows(self):
        return [json.loads(ln) for ln in self.ledger.read_text().splitlines()]

    def run_(self, replies, write=False, now=NOW):
        return rl.ingest(self.st, self.ledger, replies, now, write=write)

    def test_no_message_is_one_nothing_row_and_no_mark(self):
        got = self.run_([], write=True)
        self.assertEqual([r["action"] for r in got["rows"]], [rl.NOTHING])
        self.assertFalse((self.st / rl.MARK).exists())

    def test_dry_run_writes_nothing(self):
        before = self.ledger.read_bytes()
        got = self.run_([(NOW - 60, f"drop: {A}")])
        self.assertEqual(got["rows"][0]["action"], rl.WOULD_WRITE)
        self.assertEqual(got["would_append"], 1)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertFalse((self.st / rl.MARK).exists())

    def test_write_appends_the_owner_drop_rows_and_the_mark(self):
        before = self.ledger.read_bytes()
        got = self.run_([(NOW - 60, f"drop: {A}, {B}")], write=True)
        self.assertEqual(got["appended"], 2)
        self.assertTrue(self.ledger.read_bytes().startswith(before))
        self.assertEqual(self.rows()[2:], [DROP(A), DROP(B)])
        mark = self.st / rl.MARK
        self.assertEqual(json.loads(mark.read_text()), {"after": NOW - 60})
        self.assertEqual(oct(mark.stat().st_mode & 0o777), "0o600")
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), [rl.MARK], "no temp file left")

    def test_unknown_ids_are_ignored_and_counted(self):
        got = self.run_([(NOW - 60, f"drop: {A}, synthetic-item-unknown, synthetic-item-other")], write=True)
        self.assertEqual((got["rows"][0]["drops"], got["rows"][0]["unknown"]), (1, 2))
        self.assertEqual(self.rows()[2:], [DROP(A)])

    def test_only_unknown_ids_appends_nothing_but_moves_the_mark(self):
        before = self.ledger.read_bytes()
        got = self.run_([(NOW - 60, "drop: synthetic-item-unknown")], write=True)
        self.assertEqual(got["rows"][0]["action"], rl.IGNORE)
        self.assertEqual(got["rows"][0]["unknown"], 1)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(rl.load_mark(self.st), NOW - 60)

    def test_any_other_message_does_nothing(self):
        before = self.ledger.read_bytes()
        got = self.run_([(NOW - 90, f"please drop: {A}"), (NOW - 60, f"drop {B}"), (NOW - 30, "thanks")],
                        write=True)
        self.assertEqual([r["action"] for r in got["rows"]], [rl.IGNORE] * 3)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_every_drop_after_the_mark_counts_and_a_later_chat_line_does_not_swallow_it(self):
        self.run_([(NOW - 90, f"drop: {A}"), (NOW - 30, "thanks")], write=True)
        self.assertEqual(self.rows()[2:], [DROP(A)])
        self.assertEqual(rl.load_mark(self.st), NOW - 30)

    def test_messages_at_or_before_the_mark_are_never_read_again(self):
        self.run_([(NOW - 90, f"drop: {A}")], write=True)
        got = self.run_([(NOW - 90, f"drop: {A}"), (NOW - 60, f"drop: {B}")], write=True)
        self.assertEqual(len(got["rows"]), 1)
        self.assertEqual(self.rows()[2:], [DROP(A), DROP(B)])

    def test_a_first_run_reads_only_the_last_day_and_never_after_now(self):
        got = self.run_([(NOW - rl.FIRST_READ_S - 1, f"drop: {A}"), (NOW + 60, f"drop: {B}")], write=True)
        self.assertEqual([r["action"] for r in got["rows"]], [rl.NOTHING])
        self.assertEqual(len(self.rows()), 2)

    def test_an_item_already_dropped_by_the_owner_is_not_appended_again(self):
        self.seed(OPEN(A), DROP(A), OPEN(B))
        got = self.run_([(NOW - 60, f"drop: {A}, {B}"), (NOW - 30, f"drop: {B}")], write=True)
        self.assertEqual([(r["drops"], r["already"]) for r in got["rows"]], [(1, 1), (0, 1)])
        self.assertEqual(self.rows()[3:], [DROP(B)])

    def test_an_agent_drop_row_is_known_and_the_owner_drop_replaces_it(self):
        self.seed({"id": C, "status": "dropped", "by": "agent", "evidence": "an agent said so"})
        self.run_([(NOW - 60, f"drop: {C}")], write=True)
        self.assertEqual(rl.newest(self.ledger)[C], DROP(C))

    def test_a_drop_moves_row_ten_end_to_end(self):
        env = {"LIMITLESS_RANKED_LEDGER": str(self.ledger)}

        def row10():
            return next(r for r, _a in scorecard.measured_audits(self.st, {}, NOW, env=env)
                        if r["n"] == scorecard.TOP_ROW)
        self.assertEqual(row10()["label"], "none of the ranked items verified or dropped by the owner")
        self.run_([(NOW - 60, f"drop: {A}, {B}")], write=True)
        self.assertEqual(row10()["label"], "all of the ranked items verified or dropped by the owner")
        self.assertEqual(row10()["goal"], "met")

    def test_lines_are_words_only(self):
        got = self.run_([(NOW - 90, f"drop: {A}, synthetic-item-unknown"), (NOW - 60, "drop me a line")])
        out = "\n".join(rl.ingest_lines(got, written=False))
        self.assertTrue(no_digit(out), out)
        self.assertNotIn(A, out)
        self.assertIn("one to drop, one unknown ignored", out)
        self.assertIn("dry run: nothing written", out)


class Cli(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        self.ledger = self.home / "ranked.jsonl"
        self.ledger.write_text(json.dumps(OPEN(A)) + "\n" + json.dumps(OPEN(B)) + "\n")
        now = time.time()
        self.db = self.home / "hermes.db"
        make_db(self.db, [("user", "synthetic-private-words", now - 900),
                          ("user", f"drop: {A}, synthetic-item-unknown", now - 600),
                          ("assistant", f"drop: {B}", now - 590)], started=now - 7200)
        self.at = now - 600
        self.env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", ""), "LIMITLESS_STATE": str(self.st),
                    "LIMITLESS_CONFIG": str(self.home / "config.json"), "LIMITLESS_RANKED_LEDGER": str(self.ledger)}

    def cli(self, *args, **env):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=dict(self.env, **env),
                              capture_output=True, text=True, timeout=60)

    def test_no_db_set_reads_nothing_and_says_so(self):
        before = self.ledger.read_bytes()
        r = self.cli("ingest", "--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no Hermes DB set", r.stdout)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_no_ledger_set_reads_nothing_and_says_so(self):
        env = dict(self.env)
        del env["LIMITLESS_RANKED_LEDGER"]
        r = subprocess.run([sys.executable, "-I", str(CLI), "ingest", "--db", str(self.db), "--write"], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no ranked ledger set", r.stdout)
        self.assertFalse((self.st / rl.MARK).exists())

    def test_dry_run_then_write_from_the_session_db(self):
        before = self.ledger.read_bytes()
        r = self.cli("ingest", "--db", str(self.db))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would append one owner drop row", r.stdout)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertFalse((self.st / rl.MARK).exists())

        r = self.cli("ingest", "--write", LIMITLESS_HERMES_DB=str(self.db))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("appended one owner drop row", r.stdout)
        rows = [json.loads(ln) for ln in self.ledger.read_text().splitlines()]
        self.assertEqual(rows[2:], [DROP(A)], "only the owner's message; the assistant's line is not theirs")
        self.assertEqual(rl.load_mark(self.st), self.at)
        out = r.stdout + r.stderr
        self.assertTrue(no_digit(out), out)
        for secret in (A, "synthetic-private-words", str(self.db)):
            self.assertNotIn(secret, out)

        again = self.cli("ingest", "--write", "--db", str(self.db))
        self.assertIn("no new owner message", again.stdout)
        self.assertEqual(len(self.ledger.read_text().splitlines()), 3)


if __name__ == "__main__":
    unittest.main()
