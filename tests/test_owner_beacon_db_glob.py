"""bin/limitless-owner-beacon --db-glob: the writer expands each absolute pattern on every run, so a chat store
added after the job was printed is read by the next scheduled write without reprinting the job.

Synthetic data only: stores live in temp dirs; printed text uses /tmp/example/... Nothing sends; no network.
"""
from hermetic_env import child_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import importlib.machinery
import importlib.util
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_owner_beacon_cli import CLI, H, Base, iso  # noqa: E402
from test_owner_messages import CONTENT, make_db  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
