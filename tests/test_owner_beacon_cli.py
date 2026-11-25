"""bin/limitless-owner-beacon write --out PATH [--dbs a:b]: the newest user-message time of this machine's owner
session DBs as a content-free {"at": ISO UTC, "v": 1} file, written atomically with mode 0600.

Synthetic data only. Times are relative to the clock the CLI reads; only differences matter. Nothing sends.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import owner_messages as om  # noqa: E402
from test_owner_messages import CONTENT, make_db  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-owner-beacon"
H = 3600.0


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.now = time.time()
        self.t_new = float(int(self.now - 2 * H))
        self.a = make_db(self.dir / "a.db", [("s-cli", "user", CONTENT, self.now - 9 * H),
                                             ("s-cli", "assistant", CONTENT, self.now - 60)])
        self.b = make_db(self.dir / "b.db", [("s-tg", "user", CONTENT, self.t_new)])
        self.out = self.dir / "out" / "beacon.json"
        self.out.parent.mkdir()
        self.env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.dir),
                    "LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.dir / "none.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, env=None):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], capture_output=True, text=True,
                              env=child_env(self.env if env is None else env), timeout=30)

    def assert_one_line(self, text):
        self.assertEqual(len(text.strip().splitlines()), 1, text)
        self.assertNotIn("Traceback", text)


class Write(Base):
    def test_writes_only_the_newest_time_and_the_version(self):
        r = self.run_cli("write", "--out", str(self.out), "--dbs", os.pathsep.join([str(self.a), str(self.b)]))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.out.read_text()), {"at": iso(self.t_new), "v": 1})
        for text in (self.out.read_text(), r.stdout, r.stderr):
            for leak in ("synthetic", "s-tg", "telegram", "cli", "a.db", "b.db", str(self.dir)):
                self.assertNotIn(leak, text)

    def test_mode_0600_and_no_temp_file_left(self):
        r = self.run_cli("write", "--out", str(self.out), "--dbs", str(self.b))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(stat.S_IMODE(self.out.stat().st_mode), 0o600)
        self.assertEqual(sorted(p.name for p in self.out.parent.iterdir()), ["beacon.json"])

    def test_replaces_an_old_beacon_and_tightens_its_mode(self):
        self.out.write_text(json.dumps({"at": iso(self.now - 90 * H), "v": 1}))
        os.chmod(self.out, 0o644)
        r = self.run_cli("write", "--out", str(self.out), "--dbs", str(self.b))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.out.read_text())["at"], iso(self.t_new))
        self.assertEqual(stat.S_IMODE(self.out.stat().st_mode), 0o600)

    def test_round_trip_through_the_reader(self):
        self.run_cli("write", "--out", str(self.out), "--dbs", os.pathsep.join([str(self.a), str(self.b)]))
        here = om.newest_user_message([self.a, self.b], self.now)
        there = om.newest_user_message(None, self.now, beacons=[self.out])
        self.assertEqual((there["at"], there["sources_read"], there["sources_failed"]), (here["at"], 1, 0))

    def test_configured_dbs_are_used_without_dbs_flag(self):
        env = dict(self.env, LIMITLESS_OWNER_DBS=str(self.b))
        r = self.run_cli("write", "--out", str(self.out), env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.out.read_text())["at"], iso(self.t_new))
        cfg = self.dir / "config.json"
        cfg.write_text(json.dumps({"owner_dbs": ["rel.db"]}))
        make_db(self.st / "rel.db", [("s-cli", "user", CONTENT, self.t_new - H)])
        r = self.run_cli("write", "--out", str(self.out), env=dict(self.env, LIMITLESS_CONFIG=str(cfg)))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.out.read_text())["at"], iso(self.t_new - H))

    def test_dbs_flag_beats_the_config(self):
        env = dict(self.env, LIMITLESS_OWNER_DBS=str(self.a))
        r = self.run_cli("write", "--out", str(self.out), "--dbs", str(self.b), env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.out.read_text())["at"], iso(self.t_new))


class Unchanged(Base):
    """The same newest time as the valid beacon already at --out: the file is left as it is (bytes and mtime),
    so a copy step that runs on a schedule only moves a changed file."""
    OLD_MTIME = 1_000_000_000

    def put(self, body, mode=0o600):
        self.out.write_text(body)
        os.chmod(self.out, mode)
        os.utime(self.out, (self.OLD_MTIME, self.OLD_MTIME))

    def assert_untouched(self, body, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_one_line(r.stdout + r.stderr)
        self.assertIn("unchanged", r.stdout)
        self.assertEqual(r.stderr, "")
        self.assertEqual(self.out.read_text(), body)
        self.assertEqual(self.out.stat().st_mtime, self.OLD_MTIME)
        self.assertEqual(sorted(p.name for p in self.out.parent.iterdir()), ["beacon.json"])

    def assert_rewritten(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "limitless-owner-beacon: beacon written")
        self.assertEqual(json.loads(self.out.read_text()), {"at": iso(self.t_new), "v": 1})
        self.assertNotEqual(self.out.stat().st_mtime, self.OLD_MTIME)
        self.assertEqual(stat.S_IMODE(self.out.stat().st_mode), 0o600)
        self.assertEqual(sorted(p.name for p in self.out.parent.iterdir()), ["beacon.json"])

    def test_same_time_leaves_the_file_untouched(self):
        body = json.dumps({"at": iso(self.t_new), "v": 1}) + "\n"
        self.put(body)
        self.assert_untouched(body, self.run_cli("write", "--out", str(self.out), "--dbs", str(self.b)))

    def test_second_run_is_a_no_op(self):
        args = ("write", "--out", str(self.out), "--dbs", os.pathsep.join([str(self.a), str(self.b)]))
        self.assertEqual(self.run_cli(*args).returncode, 0)
        os.utime(self.out, (self.OLD_MTIME, self.OLD_MTIME))
        body = self.out.read_text()
        self.assert_untouched(body, self.run_cli(*args))

    def test_same_instant_written_another_way_is_still_the_same_time(self):
        body = json.dumps({"v": 1, "at": iso(self.t_new).replace("+00:00", "Z")})
        self.put(body)
        self.assert_untouched(body, self.run_cli("write", "--out", str(self.out), "--dbs", str(self.b)))

    def test_an_older_or_newer_time_is_rewritten(self):
        for other in (self.t_new - H, self.t_new + 1):
            self.put(json.dumps({"at": iso(other), "v": 1}) + "\n", mode=0o644)
            self.assert_rewritten(self.run_cli("write", "--out", str(self.out), "--dbs", str(self.b)))

    def test_not_a_valid_beacon_is_rewritten(self):
        same = iso(self.t_new)
        for body in ("", "not json", json.dumps({"at": same, "v": 2}), json.dumps({"at": same}),
                     json.dumps({"at": same[:-6], "v": 1}), json.dumps([same, 1]),
                     json.dumps({"at": same, "v": 1, "pad": "x" * om.BEACON_MAX_BYTES})):
            self.put(body)
            self.assert_rewritten(self.run_cli("write", "--out", str(self.out), "--dbs", str(self.b)))


class Nothing(Base):
    def assert_nothing_written(self, r, why):
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_one_line(r.stdout + r.stderr)
        self.assertIn(why, r.stdout + r.stderr)
        self.assertFalse(self.out.exists())
        self.assertEqual(list(self.out.parent.iterdir()), [])

    def test_no_message_from_the_person(self):
        quiet = make_db(self.dir / "quiet.db", [("s-cli", "assistant", CONTENT, self.now - H)])
        self.assert_nothing_written(self.run_cli("write", "--out", str(self.out), "--dbs", str(quiet)),
                                    "no message from the person")

    def test_no_dbs_configured(self):
        self.assert_nothing_written(self.run_cli("write", "--out", str(self.out)), "no owner session DBs")

    def test_dbs_that_cannot_be_read(self):
        self.assert_nothing_written(
            self.run_cli("write", "--out", str(self.out), "--dbs", str(self.dir / "gone.db")), "could not be read")

    def test_an_existing_beacon_is_left_alone(self):
        old = json.dumps({"at": iso(self.now - 90 * H), "v": 1})
        self.out.write_text(old)
        quiet = make_db(self.dir / "quiet.db", [])
        r = self.run_cli("write", "--out", str(self.out), "--dbs", str(quiet))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.out.read_text(), old)


class Errors(Base):
    def test_usage(self):
        for args in ((), ("write",), ("write", "--out"), ("read", "--out", str(self.out)),
                     ("write", "--out", str(self.out), "--bogus"), ("write", "--dbs", str(self.b))):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn("usage: limitless-owner-beacon write --out PATH", r.stderr)
            self.assertNotIn("Traceback", r.stderr)
        self.assertFalse(self.out.exists())
        r = self.run_cli("--help")
        self.assertEqual((r.returncode, r.stdout.startswith("usage:")), (0, True))

    def test_an_unwritable_out_is_one_line_not_a_traceback(self):
        for out in (self.dir / "missing-dir" / "b.json", self.out.parent):
            r = self.run_cli("write", "--out", str(out), "--dbs", str(self.b))
            self.assertEqual(r.returncode, 1, out)
            self.assert_one_line(r.stderr)
            self.assertIn("could not write the beacon", r.stderr)
        self.assertEqual(list(self.out.parent.iterdir()), [])

    def test_executable(self):
        self.assertTrue(os.access(CLI, os.X_OK))


if __name__ == "__main__":
    unittest.main()
