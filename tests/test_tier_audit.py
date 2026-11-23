"""tier_audit: one content-free JSON line per injection, proving which privacy tier the model saw.

Synthetic cards only: the marker string below stands in for card text and must never reach the log.
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from limitless import tier_audit  # noqa: E402

MARKER = "zebra-marker-card-text"
CARD_T1 = f"[limitless] state card\nwindow: peak ({MARKER})\nsleep short (proxy)"
CARD_DIGITS = f"[limitless] state card\nsleep short (proxy, 5 h) {MARKER}"
NOW = 1894708800.0


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / "audit.jsonl"
        self.env = {tier_audit.ENV_KEY: str(self.log)}
        self.home = Path(self.tmp.name) / "home"

    def rows(self):
        return [json.loads(ln) for ln in self.log.read_text().splitlines()]


class Record(Base):
    def test_one_line_per_record_with_the_documented_fields(self):
        for _ in range(2):
            self.assertTrue(tier_audit.record(tier_audit.event("pre_llm_call", CARD_T1, False, now=NOW),
                                              env=self.env, home=self.home))
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows[0]), {"at", "hook", "tier", "lines", "digits", "opt_in", "sha256", "blocked"})
        self.assertEqual(rows[0]["hook"], "pre_llm_call")
        self.assertEqual(rows[0]["tier"], "T1")
        self.assertEqual(rows[0]["lines"], 3)
        self.assertEqual(rows[0]["digits"], 0)
        self.assertIs(rows[0]["opt_in"], False)
        self.assertIs(rows[0]["blocked"], False)
        self.assertEqual(len(rows[0]["sha256"]), 64)
        self.assertTrue(rows[0]["at"].endswith("Z"))

    def test_the_card_text_is_never_written(self):
        ev = dict(tier_audit.event("pre_llm_call", CARD_DIGITS, True, now=NOW), text=CARD_DIGITS)
        tier_audit.record(ev, env=self.env, home=self.home)
        raw = self.log.read_text()
        self.assertNotIn(MARKER, raw)
        self.assertNotIn("text", json.loads(raw))

    def test_file_is_created_0600_and_only_appended(self):
        tier_audit.record(tier_audit.event("pre_llm_call", CARD_T1, False, now=NOW), env=self.env, home=self.home)
        self.assertEqual(stat.S_IMODE(os.stat(self.log).st_mode), 0o600)
        first = self.log.read_text()
        tier_audit.record(tier_audit.event("pre_llm_call", CARD_T1, False, now=NOW), env=self.env, home=self.home)
        self.assertTrue(self.log.read_text().startswith(first))

    def test_off_when_no_path_is_configured(self):
        self.assertIsNone(tier_audit.audit_path({}, self.home))
        self.assertFalse(tier_audit.record(tier_audit.event("pre_llm_call", CARD_T1, False, now=NOW),
                                           env={}, home=self.home))

    def test_config_audit_path(self):
        cfg = Path(self.tmp.name) / "config.json"
        cfg.write_text(json.dumps({"audit_path": str(self.log)}))
        env = {"LIMITLESS_CONFIG": str(cfg)}
        self.assertEqual(tier_audit.audit_path(env, self.home), self.log)
        tier_audit.record(tier_audit.event("pre_llm_call", CARD_T1, False, now=NOW), env=env, home=self.home)
        self.assertEqual(len(self.rows()), 1)

    def test_never_raises(self):
        env = {tier_audit.ENV_KEY: str(Path(self.tmp.name) / "no" / "such" / "dir" / "a.jsonl")}
        self.assertFalse(tier_audit.record(tier_audit.event("pre_llm_call", CARD_T1, False, now=NOW), env=env))
        self.assertFalse(tier_audit.record(None, env=self.env, home=self.home))
        self.assertFalse(tier_audit.record({"tier": object()}, env=self.env, home=self.home))


class Check(Base):
    def write(self, *lines):
        self.log.write_text("".join(ln + "\n" for ln in lines))

    def row(self, at, tier="T1", opt_in=False, blocked=False):
        return json.dumps({"at": at, "hook": "pre_llm_call", "tier": tier, "lines": 3,
                           "digits": 0 if tier == "T1" else 2, "opt_in": opt_in, "sha256": "0" * 64,
                           "blocked": blocked})

    def test_counts(self):
        self.write(self.row("2030-01-14T07:00:00Z"), self.row("2030-01-15T07:00:00Z"),
                   self.row("2030-01-15T08:00:00Z", "T0", opt_in=True),
                   self.row("2030-01-15T09:00:00Z", "T0", blocked=True),
                   self.row("2030-01-15T10:00:00Z", "T0"))
        self.assertEqual(tier_audit.check(self.log), {"injections": 4, "t0_with_opt_in": 1,
                                                      "t0_without_opt_in": 1, "blocked": 1})

    def test_since(self):
        self.write(self.row("2030-01-14T07:00:00Z", "T0"), self.row("2030-01-15T07:00:00Z"))
        got = tier_audit.check(self.log, since="2030-01-15T00:00:00Z")
        self.assertEqual(got, {"injections": 1, "t0_with_opt_in": 0, "t0_without_opt_in": 0, "blocked": 0})
        self.assertEqual(tier_audit.check(self.log, since=1894665600.0)["injections"], 1)

    def test_bad_lines_are_skipped(self):
        self.write("not json", "[1, 2]", "{}", json.dumps({"tier": "T9", "at": "2030-01-15T07:00:00Z"}),
                   json.dumps({"tier": "T0", "at": "never"}), self.row("2030-01-15T07:00:00Z"), "{\"at\": ")
        self.assertEqual(tier_audit.check(self.log), {"injections": 1, "t0_with_opt_in": 0,
                                                      "t0_without_opt_in": 0, "blocked": 0})

    def test_missing_or_broken_file_is_zero_counts(self):
        zero = {"injections": 0, "t0_with_opt_in": 0, "t0_without_opt_in": 0, "blocked": 0}
        self.assertEqual(tier_audit.check(Path(self.tmp.name) / "nope.jsonl"), zero)
        self.assertEqual(tier_audit.check(Path(self.tmp.name)), zero)  # a directory
        self.log.write_bytes(b"\xff\xfe\x00garbage")
        self.assertEqual(tier_audit.check(self.log), zero)
        self.assertEqual(tier_audit.check(None), zero)

    def test_what_record_writes_check_reads(self):
        for text, opt in ((CARD_T1, False), (CARD_DIGITS, True), (CARD_DIGITS, False)):
            tier_audit.gate("pre_llm_call", text, opt, env=self.env, home=self.home, now=NOW)
        self.assertEqual(tier_audit.check(self.log), {"injections": 2, "t0_with_opt_in": 1,
                                                      "t0_without_opt_in": 0, "blocked": 1})


class Cli(Base):
    BIN = ROOT / "bin" / "limitless-tier-audit"

    def run_cli(self, *args, env=None):
        import subprocess
        e = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.home)}
        e.update(env or {})
        return subprocess.run([sys.executable, "-I", str(self.BIN), *args], capture_output=True, text=True,
                              env=e, timeout=30)

    def test_plain_words_and_exit_zero(self):
        tier_audit.gate("pre_llm_call", CARD_T1, False, env=self.env, home=self.home, now=NOW)
        tier_audit.gate("pre_llm_call", CARD_DIGITS, False, env=self.env, home=self.home, now=NOW)
        p = self.run_cli(str(self.log))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.splitlines(), [
            "1 injection", "0 with raw numbers under the opt-in", "0 with raw numbers without the opt-in",
            "1 blocked (dropped, not sent)"])
        self.assertNotIn(MARKER, p.stdout)

    def test_exit_one_on_a_leak(self):
        self.log.write_text(json.dumps({"at": "2030-01-15T07:00:00Z", "tier": "T0", "opt_in": False,
                                        "blocked": False, "sha256": "0" * 64}) + "\n")
        p = self.run_cli(env=self.env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("1 with raw numbers without the opt-in", p.stdout)

    def test_since_and_days(self):
        self.log.write_text(json.dumps({"at": "2030-01-14T07:00:00Z", "tier": "T0", "opt_in": False,
                                        "blocked": False, "sha256": "0" * 64}) + "\n")
        p = self.run_cli(str(self.log), "--since", "2030-01-15T00:00:00Z")
        self.assertEqual((p.returncode, p.stdout.splitlines()[0]), (0, "0 injections"))
        p = self.run_cli(str(self.log), "--days", "7")  # the row is from 2030: still inside "since 7 days ago"
        self.assertEqual(p.returncode, 1)

    def test_missing_file_or_no_path_is_zero_never_a_traceback(self):
        for args, env in (((str(Path(self.tmp.name) / "nope.jsonl"),), {}), ((), {}),
                          (("--since", "not a date"), self.env), (("--days", "x"), self.env)):
            p = self.run_cli(*args, env=env)
            self.assertNotIn("Traceback", p.stderr)
            self.assertIn(p.returncode, (0, 2))
        p = self.run_cli()
        self.assertEqual((p.returncode, p.stdout.splitlines()[0]), (0, "0 injections"))

    def test_writes_nothing(self):
        cache = ROOT / "bin" / "__pycache__"
        mine = lambda: sorted(p.name for p in cache.glob("limitless-tier-audit*")) if cache.is_dir() else []
        before = mine()   # other bin scripts may have their own bytecode here (a deployed tree); only ours counts
        self.run_cli(env=self.env)
        self.assertFalse(self.log.exists())
        self.assertEqual(mine(), before)
        self.assertEqual(before, [])


if __name__ == "__main__":
    unittest.main()
