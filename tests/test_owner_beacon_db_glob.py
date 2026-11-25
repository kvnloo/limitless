"""bin/limitless-owner-beacon --db-glob: the writer expands each absolute pattern on every run, so a chat store
added after the job was printed is read by the next scheduled write without reprinting the job.

Synthetic data only: stores live in temp dirs; printed text uses /tmp/example/... Nothing sends; no network.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import importlib.machinery
import importlib.util
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_owner_beacon_cli import CLI, H, Base, iso  # noqa: E402
from test_owner_beacon_schedule import Base as ScheduleBase  # noqa: E402
from test_owner_beacon_schedule import DEST, LABEL, OUT, SCP, systemd_words, units, writer  # noqa: E402
from test_owner_messages import CONTENT, make_db  # noqa: E402

PATTERN = "/tmp/example/homes/*/state.db"
ODD_PATTERN = "/tmp/example/it's [a-z]?/*.db"   # a space, a quote, a class and a ?: none expanded by the shell


def load_cli():
    """The writer script as a module, to call its path expansion directly."""
    loader = importlib.machinery.SourceFileLoader("limitless_owner_beacon_cli", str(CLI))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class GlobBase(Base):
    def setUp(self):
        super().setUp()
        self.homes = self.dir / "homes"
        self.pattern = str(self.homes / "*" / "state.db")

    def home_db(self, name, t):
        (self.homes / name).mkdir(parents=True)
        return make_db(self.homes / name / "state.db", [("s-cli", "user", CONTENT, t)])

    def beacon_at(self):
        return json.loads(self.out.read_text())["at"]


class WriteGlob(GlobBase):
    def test_each_run_expands_the_pattern_again(self):
        self.home_db("one", self.t_new - H)
        args = ("write", "--out", str(self.out), "--db-glob", self.pattern)
        r = self.run_cli(*args)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "limitless-owner-beacon: beacon written"), r.stderr)
        self.assertEqual(self.beacon_at(), iso(self.t_new - H))
        self.home_db("two", self.t_new)       # a new agent home, added after the first run
        r = self.run_cli(*args)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.beacon_at(), iso(self.t_new))

    def test_several_patterns_and_dbs_together(self):
        self.home_db("one", self.t_new - 3 * H)
        r = self.run_cli("write", "--out", str(self.out), "--db-glob", self.pattern,
                         "--db-glob", str(self.dir / "b*.db"), "--dbs", str(self.a))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.beacon_at(), iso(self.t_new))      # b.db, matched by the second pattern

    def test_a_pattern_that_matches_nothing_is_not_an_error(self):
        r = self.run_cli("write", "--out", str(self.out), "--db-glob", self.pattern)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_one_line(r.stdout + r.stderr)
        self.assertIn("nothing written", r.stdout)
        self.assertFalse(self.out.exists())
        r = self.run_cli("write", "--out", str(self.out), "--db-glob", self.pattern, "--dbs", str(self.b))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.beacon_at(), iso(self.t_new))

    def test_the_flag_beats_the_config(self):
        newer = make_db(self.dir / "newer.db", [("s-cli", "user", CONTENT, self.t_new + H)])
        self.home_db("one", self.t_new)
        r = self.run_cli("write", "--out", str(self.out), "--db-glob", self.pattern,
                         env=dict(self.env, LIMITLESS_OWNER_DBS=str(newer)))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.beacon_at(), iso(self.t_new))

    def test_a_missing_value_is_usage(self):
        r = self.run_cli("write", "--out", str(self.out), "--db-glob")
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage: limitless-owner-beacon write --out PATH", r.stderr)
        self.assertIn("--db-glob", r.stderr)


RELATIVE = ("homes/*/state.db", "~/homes/*/state.db", "./*.db", "*.db")
NEWLINE = ("/tmp/example/a\n*.db", "/tmp/example/a\r*.db")


class WriteRefusals(GlobBase):
    """Exit 2, one line on stderr, nothing written: a relative pattern (the job does not run in this directory
    or expand ~) and a pattern with a newline."""

    def assert_refused(self, word, pattern):
        r = self.run_cli("write", "--out", str(self.out), "--dbs", str(self.b), "--db-glob", pattern)
        self.assertEqual((r.returncode, r.stdout), (2, ""), pattern)
        self.assert_one_line(r.stderr)
        self.assertIn("limitless-owner-beacon: refused:", r.stderr)
        self.assertIn(word, r.stderr)
        self.assertFalse(self.out.exists())

    def test_a_relative_pattern(self):
        for pattern in RELATIVE:
            self.assert_refused("--db-glob", pattern)

    def test_a_pattern_with_a_newline(self):
        for pattern in NEWLINE:
            self.assert_refused("newline", pattern)


class ScheduleRefusals(ScheduleBase):
    def assert_refused(self, word, pattern):
        for kind in ("launchd", "systemd"):
            r = self.run_cli("schedule", "--print", "--kind", kind, "--out", OUT, "--every", "60",
                             "--db-glob", pattern)
            self.assertEqual((r.returncode, r.stdout), (2, ""), (kind, pattern))
            self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
            self.assertNotIn("Traceback", r.stderr)
            self.assertIn("limitless-owner-beacon: refused:", r.stderr)
            self.assertIn(word, r.stderr)
            self.assertEqual(sorted(self.home.iterdir()), [])

    def test_a_relative_pattern(self):
        for pattern in RELATIVE:
            self.assert_refused("--db-glob", pattern)

    def test_a_pattern_with_a_newline(self):
        for pattern in NEWLINE:
            self.assert_refused("newline", pattern)


class Expansion(GlobBase):
    """The DB list the writer reads: --dbs in order, then each pattern's matches sorted, each path once."""

    def setUp(self):
        super().setUp()
        self.cli = load_cli()
        self.one = self.home_db("one", self.t_new)
        self.two = self.home_db("two", self.t_new)

    def test_matches_are_sorted(self):
        self.assertEqual(self.cli.db_paths(None, [self.pattern]), [self.one, self.two])

    def test_a_path_given_twice_is_read_once(self):
        got = self.cli.db_paths(str(self.two), [self.pattern, str(self.homes / "o*" / "state.db")])
        self.assertEqual(got, [self.two, self.one])

    def test_no_match_and_no_dbs_is_none(self):
        self.assertIsNone(self.cli.db_paths(None, [str(self.dir / "none" / "*.db")]))


class PrintedJob(ScheduleBase):
    """schedule --print passes each pattern through to the writer as it was given: shell-quoted (so /bin/sh does
    not expand it), escaped for systemd, never expanded at print time."""

    def writer_step(self, kind, *args):
        text = self.schedule("--kind", kind, *args)
        if kind == "launchd":
            words = plistlib.loads(text.encode())["ProgramArguments"]
        else:
            words = systemd_words(units(text)[LABEL + ".service"]["Service"]["ExecStart"])
        return self.sh_steps(words)

    def test_launchd_carries_the_literal_patterns(self):
        steps = self.writer_step("launchd", "--out", OUT, "--every", "60", "--copy-to", DEST,
                                 "--db", "/tmp/example/a.db", "--db-glob", PATTERN, "--db-glob", ODD_PATTERN)
        self.assertEqual(steps, [writer(OUT, ["/tmp/example/a.db"]) + ["--db-glob", PATTERN, "--db-glob", ODD_PATTERN],
                                 SCP + [OUT, DEST]])

    def test_systemd_carries_the_literal_patterns_with_a_dollar_and_a_percent(self):
        odd = "/tmp/example/50% $HOME/*/state.db"
        steps = self.writer_step("systemd", "--label", LABEL, "--out", OUT, "--every", "60", "--copy-to", DEST,
                                 "--db-glob", PATTERN, "--db-glob", odd)
        self.assertEqual(steps, [writer(OUT) + ["--db-glob", PATTERN, "--db-glob", odd], SCP + [OUT, DEST]])

    def test_a_store_added_after_the_job_was_printed_is_read_by_the_next_write(self):
        now = time.time()
        for kind in ("launchd", "systemd"):
            with tempfile.TemporaryDirectory() as d:
                homes, out = Path(d) / "homes", Path(d) / "beacon.json"
                pattern = str(homes / "*" / "state.db")
                (homes / "one").mkdir(parents=True)
                make_db(homes / "one" / "state.db", [("s-cli", "user", CONTENT, now - 3 * H)])
                [argv] = self.writer_step(kind, "--label", LABEL, "--out", str(out), "--every", "60",
                                          "--db-glob", pattern)
                self.assertEqual(argv[-2:], ["--db-glob", pattern], kind)
                self.assertEqual(self.run_step(argv), 0, kind)
                self.assertEqual(json.loads(out.read_text())["at"], iso(float(int(now - 3 * H))), kind)
                (homes / "two").mkdir()     # a new agent home: the job is not printed again
                make_db(homes / "two" / "state.db", [("s-tg", "user", CONTENT, now - H)])
                self.assertEqual(self.run_step(argv), 0, kind)
                self.assertEqual(json.loads(out.read_text())["at"], iso(float(int(now - H))), kind)

    def run_step(self, argv):
        """Run the printed writer argv as the job would (no shell needed: the words are already split)."""
        r = subprocess.run(argv, capture_output=True, text=True, env=child_env(self.env), cwd=str(self.home),
                           timeout=30)
        self.assertEqual(r.stderr, "")
        return r.returncode


if __name__ == "__main__":
    unittest.main()
