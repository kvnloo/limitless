"""The ranked ledger's agent writes: bin/limitless-ranked add / list.

An agent row is {"id", "status": open | built | verified, "by": "agent", "evidence"}; verified needs evidence and
dropped is refused (only the owner drops, by reply). Dry run unless --write; append-only, 0600, flock. Row ten of
the scorecard moves from unknown to words once rows are written. Synthetic ids only; nothing sends.
"""
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import ranked_ledger, scorecard, tier_audit  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-ranked"
NOW = 1894708800.0
A, B, C, D = ("synthetic-item-a", "synthetic-item-b", "synthetic-item-c", "synthetic-item-d")


def passes_tier_audit(text):
    """True when the text would go out without the raw opt-in (no digit: tier T1, not blocked)."""
    ev = tier_audit.event("cli:limitless-ranked", text, opt_in=False, now=NOW)
    return ev["tier"] == tier_audit.T1 and not ev["blocked"]


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        self.ledger = self.home / "ranked.jsonl"
        self.env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", ""), "LIMITLESS_STATE": str(self.st),
                    "LIMITLESS_CONFIG": str(self.home / "config.json"),
                    "LIMITLESS_RANKED_LEDGER": str(self.ledger)}

    def cli(self, *args, **env):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=dict(self.env, **env),
                              capture_output=True, text=True, timeout=60)

    def rows(self):
        return [json.loads(ln) for ln in self.ledger.read_text().splitlines()]

    def seed(self, *rows):
        self.ledger.write_text("".join(json.dumps(r) + "\n" for r in rows))
        os.chmod(self.ledger, 0o600)

    def row10(self):
        cfg = {"state": str(self.st)}
        env = {"LIMITLESS_RANKED_LEDGER": str(self.ledger)}
        for row, audit in scorecard.measured_audits(self.st, cfg, NOW, env=env, home=self.home):
            if row["n"] == scorecard.TOP_ROW:
                return row, audit
        self.fail("no row ten")


class Add(Base):
    def test_dry_run_writes_nothing_and_says_what_it_would_append(self):
        r = self.cli("add", A, "open")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.ledger.exists())
        self.assertIn("would append one row", r.stdout)
        self.assertIn("dry run: nothing written", r.stdout)

    def test_write_appends_one_agent_row_mode_0600(self):
        r = self.cli("add", A, "built", "--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("appended one row", r.stdout)
        self.assertEqual(self.rows(), [{"id": A, "status": "built", "by": "agent", "evidence": ""}])
        self.assertEqual(oct(self.ledger.stat().st_mode & 0o777), "0o600")

    def test_verified_with_evidence_is_appended(self):
        r = self.cli("add", A, "verified", "--evidence", "a synthetic receipt", "--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows(), [{"id": A, "status": "verified", "by": "agent",
                                        "evidence": "a synthetic receipt"}])

    def test_verified_without_evidence_is_refused_exit_two_nothing_written(self):
        for extra in ((), ("--evidence", ""), ("--evidence", "   ")):
            r = self.cli("add", A, "verified", *extra, "--write")
            self.assertEqual(r.returncode, 2, (extra, r.stdout, r.stderr))
            self.assertIn("refused", r.stderr)
            self.assertFalse(self.ledger.exists(), extra)

    def test_dropped_is_refused_exit_two_only_the_owner_drops(self):
        self.seed({"id": A, "status": "open", "by": "agent", "evidence": ""})
        before = self.ledger.read_bytes()
        r = self.cli("add", A, "dropped", "--evidence", "an agent said so", "--write")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("only the owner drops", r.stderr)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_any_other_status_is_refused(self):
        for status in ("done", "owner", "VERIFIED", ""):
            r = self.cli("add", A, status, "--evidence", "x", "--write")
            self.assertEqual(r.returncode, 2, status)
        self.assertFalse(self.ledger.exists())

    def test_there_is_no_way_to_set_by(self):
        r = self.cli("add", A, "verified", "--evidence", "x", "--by", "owner", "--write")
        self.assertEqual(r.returncode, 2)
        self.assertFalse(self.ledger.exists())

    def test_a_malformed_id_is_refused(self):
        for bad in ("", " ", "two words", "a,b", "-leading-dash", "x" * 81, "line\nbreak"):
            r = self.cli("add", bad, "open", "--write")
            self.assertEqual(r.returncode, 2, repr(bad))
        self.assertFalse(self.ledger.exists())

    def test_an_agent_cannot_reopen_an_item_the_owner_dropped(self):
        self.seed({"id": A, "status": "dropped", "by": "owner", "evidence": "owner reply"})
        before = self.ledger.read_bytes()
        r = self.cli("add", A, "verified", "--evidence", "a synthetic receipt", "--write")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("owner dropped", r.stderr)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_append_only_old_rows_are_never_rewritten(self):
        self.cli("add", A, "open", "--write")
        first = self.ledger.read_bytes()
        self.cli("add", A, "built", "--write")
        self.cli("add", B, "open", "--write")
        self.assertTrue(self.ledger.read_bytes().startswith(first))
        self.assertEqual([(r["id"], r["status"]) for r in self.rows()], [(A, "open"), (A, "built"), (B, "open")])
        for ln in self.ledger.read_text().splitlines():
            self.assertIsInstance(json.loads(ln), dict)

    def test_a_torn_last_line_is_kept_and_the_new_row_starts_on_its_own_line(self):
        self.ledger.write_text(json.dumps({"id": A, "status": "open", "by": "agent", "evidence": ""}) + "\n{\"id\": ")
        before = self.ledger.read_bytes()
        self.cli("add", B, "open", "--write")
        self.assertTrue(self.ledger.read_bytes().startswith(before))
        lines = self.ledger.read_text().splitlines()
        self.assertEqual(json.loads(lines[-1])["id"], B)
        self.assertEqual(sorted(scorecard._ledger_rows(self.ledger.read_text())), [A, B])

    def test_an_existing_wider_mode_is_made_0600(self):
        self.seed({"id": A, "status": "open", "by": "agent", "evidence": ""})
        os.chmod(self.ledger, 0o644)
        self.cli("add", B, "open", "--write")
        self.assertEqual(oct(self.ledger.stat().st_mode & 0o777), "0o600")

    def test_no_ledger_set_writes_nothing_and_says_so(self):
        env = dict(self.env)
        del env["LIMITLESS_RANKED_LEDGER"]
        r = subprocess.run([sys.executable, "-I", str(CLI), "add", A, "open", "--write"], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no ranked ledger set", r.stdout + r.stderr)
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), ["state"])

    def test_the_output_passes_the_tier_audit_and_never_echoes_the_id_or_evidence(self):
        for args in (("add", A, "open"), ("add", A, "verified", "--evidence", "receipt-text-xyz", "--write"),
                     ("add", A, "verified", "--write"), ("add", B, "dropped", "--write")):
            r = self.cli(*args)
            out = r.stdout + r.stderr
            self.assertTrue(passes_tier_audit(out), out)
            self.assertNotIn(A, out)
            self.assertNotIn("receipt-text-xyz", out)


class Lock(Base):
    def test_append_waits_for_the_exclusive_lock(self):
        self.seed({"id": A, "status": "open", "by": "agent", "evidence": ""})
        before = self.ledger.read_bytes()
        fd = os.open(self.ledger, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            t = threading.Thread(target=ranked_ledger.add, args=(self.ledger, B, "open"), kwargs={"write": True})
            t.start()
            time.sleep(0.3)
            self.assertEqual(self.ledger.read_bytes(), before, "appended while another writer held the lock")
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        t.join(10)
        self.assertEqual([r["id"] for r in self.rows()], [A, B])


class Library(Base):
    def test_agent_rows_never_say_dropped(self):
        for status in ranked_ledger.AGENT_STATUSES:
            ev = "a synthetic receipt" if status == "verified" else None
            row = ranked_ledger.agent_row(A, status, ev)
            self.assertEqual(row["by"], ranked_ledger.AGENT)
            self.assertNotEqual(row["status"], "dropped")
        self.assertNotIn("dropped", ranked_ledger.AGENT_STATUSES)
        with self.assertRaises(ranked_ledger.Refused):
            ranked_ledger.agent_row(A, "dropped", "x")
        self.assertNotEqual(ranked_ledger.AGENT, scorecard.OWNER)

    def test_dry_run_add_returns_the_row_and_writes_nothing(self):
        got = ranked_ledger.add(self.ledger, A, "open")
        self.assertEqual(got, {"id": A, "status": "open", "by": "agent", "evidence": ""})
        self.assertFalse(self.ledger.exists())


class List(Base):
    def test_words_for_each_count_and_the_row_ten_label(self):
        self.seed({"id": A, "status": "verified", "by": "owner", "evidence": "a synthetic receipt"},
                  {"id": B, "status": "dropped", "by": "owner", "evidence": ""},
                  {"id": C, "status": "verified", "by": "agent", "evidence": ""},
                  {"id": D, "status": "dropped", "by": "agent", "evidence": "an agent said so"})
        r = self.cli("list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), [
            "ranked ledger: some of the ranked items verified or dropped by the owner",
            "verified with evidence: some",
            "dropped by the owner: some",
            "open or built: none",
            "not counted (verified without evidence, or dropped by someone else): some",
        ])
        self.assertTrue(passes_tier_audit(r.stdout))
        for i in (A, B, C, D):
            self.assertNotIn(i, r.stdout)

    def test_raw_gives_the_counts(self):
        self.seed({"id": A, "status": "verified", "by": "agent", "evidence": "a synthetic receipt"},
                  {"id": B, "status": "open", "by": "agent", "evidence": ""})
        r = self.cli("list", "--raw")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout.splitlines()[-1])
        self.assertEqual(got, {"items": 2, "verified": 1, "owner_dropped": 0, "not_counted": 0, "open": 1})

    def test_no_ledger_or_no_rows_is_unknown_in_words(self):
        r = self.cli("list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[0], "ranked ledger: unknown: the ranked ledger is missing or cannot "
                                                   "be read")
        self.ledger.write_text("")
        self.assertEqual(self.cli("list").stdout.splitlines()[0],
                         "ranked ledger: unknown: the ranked ledger has no rows")
        env = dict(self.env)
        del env["LIMITLESS_RANKED_LEDGER"]
        r = subprocess.run([sys.executable, "-I", str(CLI), "list"], env=env, capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertIn("unknown: no ranked ledger set", r.stdout)
        self.assertTrue(passes_tier_audit(r.stdout))


class RowTen(Base):
    def test_row_ten_moves_from_unknown_to_words_after_writes(self):
        row, audit = self.row10()
        self.assertEqual(row["goal"], "unknown")
        self.assertTrue(row["label"].startswith(scorecard.UNKNOWN_PREFIX))
        self.assertIsNone(audit)

        self.assertEqual(self.cli("add", A, "open", "--write").returncode, 0)
        self.assertEqual(self.cli("add", B, "verified", "--evidence", "a synthetic receipt", "--write").returncode, 0)
        row, audit = self.row10()
        self.assertEqual(row["label"], "some of the ranked items verified or dropped by the owner")
        self.assertEqual(row["goal"], "not met")
        self.assertNotRegex(row["label"], r"\d")

        self.assertEqual(self.cli("add", A, "verified", "--evidence", "a synthetic receipt", "--write").returncode, 0)
        row, audit = self.row10()
        self.assertEqual(row["label"], "all of the ranked items verified or dropped by the owner")
        self.assertEqual(row["goal"], "met")
        self.assertEqual(audit["verified"], 2)

    def test_verified_without_evidence_never_counts(self):
        self.cli("add", A, "verified", "--write")       # refused
        self.cli("add", A, "open", "--write")
        self.seed(*self.rows(), {"id": A, "status": "verified", "by": "agent", "evidence": " "})
        row, audit = self.row10()
        self.assertEqual(row["goal"], "not met")
        self.assertEqual((audit["verified"], audit["not_counted"]), (0, 1))


if __name__ == "__main__":
    unittest.main()
