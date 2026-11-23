"""bin/limitless-noop-export [--write]: a dry run by default; --write merges the nightly rows into config
sleep_file and presleep_hr_file atomically (0600), so a rerun is unchanged and byte-identical.

Synthetic DBs only (tests/noop_fixture.py). UTC stands in for the local zone. Nothing here sends.
"""
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import noop_export as nx  # noqa: E402
from noop_fixture import PHONE, RING, hr_before, make_db, stages  # noqa: E402

CLI = ROOT / "bin" / "limitless-noop-export"
UTC = timezone.utc
H = 3600
FIRST = date(2030, 1, 1)


def at(d, hh, mm=0):
    return int(datetime.combine(d, time(hh, mm), UTC).timestamp())


def nights(n, first=FIRST, bpm=60):
    sessions, hr = [], []
    for i in range(n):
        on = at(first + timedelta(days=i), 23)
        sessions.append((RING, on, on + 8 * H, 0.9, stages(on, 7 * H, H)))
        hr += hr_before(RING, on, bpm + (i % 3))
    return sessions, hr


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.cfg_path = self.dir / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg_path), "LIMITLESS_STATE": str(self.st)}
        self.db = self.st / "noop-copy.db"
        self.sleep = self.st / "sleep.jsonl"
        self.pre = self.st / "presleep-hr.jsonl"

    def config(self, **kw):
        cfg = {"noop_db": "noop-copy.db", "sleep_file": "sleep.jsonl", "presleep_hr_file": "presleep-hr.jsonl"}
        cfg.update(kw)
        self.cfg_path.write_text(json.dumps({k: v for k, v in cfg.items() if v is not None}))

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = nx.main(list(args), env=self.env, home=self.dir, tz=UTC, out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def rows(self, p):
        return [json.loads(ln) for ln in p.read_text().splitlines()]


class DryRun(Base):
    def test_the_default_is_a_dry_run_that_writes_nothing_and_counts_in_words(self):
        self.config()
        make_db(self.db, sessions=nights(3)[0], hr=nights(3)[1])
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("dry run: three nights of wearable sleep and three nights of pre-sleep heart rate", out)
        self.assertIn("nothing written", out)
        self.assertNotRegex(out, r"\d")
        self.assertFalse(self.sleep.exists())
        self.assertFalse(self.pre.exists())

    def test_no_db_configured_is_exit_zero_with_one_reason(self):
        self.config(noop_db=None)
        code, out, _ = self.run_main("--write")
        self.assertEqual((code, out.strip()), (0, nx.NO_DB))
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), [])

    def test_a_schema_mismatch_is_exit_zero_with_one_reason_and_writes_nothing(self):
        self.config()
        make_db(self.db, drop="hrSample")
        code, out, _ = self.run_main("--write")
        self.assertEqual((code, out.strip()), (0, nx.SCHEMA_PREFIX + "no table hrSample"))
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), ["noop-copy.db"])

    def test_a_missing_db_is_exit_zero_with_one_reason(self):
        self.config()
        code, out, _ = self.run_main("--write")
        self.assertEqual((code, out.strip()), (0, nx.NO_FILE))

    def test_bad_arguments_are_exit_two_and_usage(self):
        self.config()
        code, _, err = self.run_main("--wrtie")
        self.assertEqual(code, 2)
        self.assertIn("usage: limitless-noop-export", err)

    def test_paths_come_from_config_and_are_never_printed(self):
        sub = self.st / "wear"
        self.config(noop_db=str(self.dir / "elsewhere.db"), sleep_file="wear/s.jsonl", presleep_hr_file="wear/p.jsonl")
        make_db(self.dir / "elsewhere.db", sessions=nights(2)[0], hr=nights(2)[1])
        code, out, _ = self.run_main("--write")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.rows(sub / "s.jsonl")), 2)
        self.assertEqual(len(self.rows(sub / "p.jsonl")), 2)
        self.assertNotIn(str(self.dir), out)
        self.assertNotIn("jsonl", out)


class Write(Base):
    def test_write_creates_both_files_0600_with_the_readers_row_shapes(self):
        self.config()
        s, hr = nights(2)
        make_db(self.db, sessions=s, hr=hr)
        code, out, _ = self.run_main("--write")
        self.assertEqual(code, 0)
        self.assertIn("sleep file: written, two nights new or changed", out)
        self.assertIn("pre-sleep heart-rate file: written, two nights new or changed", out)
        for p in (self.sleep, self.pre):
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(self.rows(self.sleep)[0], {"night": "2030-01-01", "asleep_s": 7 * H, "source": "noop",
                                                    "start": "2030-01-01T23:00:00Z", "end": "2030-01-02T07:00:00Z"})
        self.assertEqual(self.rows(self.pre)[1], {"night": "2030-01-02", "bpm": 61.0, "modality": "measured"})
        self.assertEqual(sorted(p.name for p in self.st.iterdir()),
                         ["noop-copy.db", "presleep-hr.jsonl", "sleep.jsonl"])   # no temp file left

    def test_a_rerun_is_unchanged_and_byte_identical(self):
        self.config()
        s, hr = nights(4)
        make_db(self.db, sessions=s, hr=hr)
        self.run_main("--write")
        before = (self.sleep.read_bytes(), self.pre.read_bytes())
        mtimes = (self.sleep.stat().st_mtime_ns, self.pre.stat().st_mtime_ns)
        code, out, _ = self.run_main("--write")
        self.assertEqual(code, 0)
        self.assertIn("sleep file: unchanged", out)
        self.assertIn("pre-sleep heart-rate file: unchanged", out)
        self.assertEqual((self.sleep.read_bytes(), self.pre.read_bytes()), before)
        self.assertEqual((self.sleep.stat().st_mtime_ns, self.pre.stat().st_mtime_ns), mtimes)

    def test_merge_by_night_keeps_older_nights_and_other_rows_and_replaces_its_own(self):
        self.config()
        other = {"night": "2030-01-02", "asleep_s": 20000, "source": "other-export"}
        old_own = {"night": "2030-01-02", "asleep_s": 100, "source": "noop"}
        kept = {"night": "2029-12-01", "asleep_s": 25000, "source": "noop"}
        self.sleep.write_text("".join(json.dumps(r) + "\n" for r in (old_own, other, kept)))
        phone = {"night": "2030-01-02", "bpm": 70, "modality": "phone"}
        self.pre.write_text(json.dumps({"night": "2030-01-02", "bpm": 99, "modality": "measured"}) + "\n"
                            + json.dumps(phone) + "\n")
        s, hr = nights(2)
        make_db(self.db, sessions=s, hr=hr)
        code, out, _ = self.run_main("--write")
        self.assertEqual(code, 0)
        got = self.rows(self.sleep)
        self.assertEqual([(r["night"], r["source"], r["asleep_s"]) for r in got],
                         [("2029-12-01", "noop", 25000), ("2030-01-01", "noop", 7 * H),
                          ("2030-01-02", "noop", 7 * H), ("2030-01-02", "other-export", 20000)])
        pre = self.rows(self.pre)
        self.assertEqual([(r["night"], r["modality"], r["bpm"]) for r in pre],
                         [("2030-01-01", "measured", 60.0), ("2030-01-02", "measured", 61.0),
                          ("2030-01-02", "phone", 70)])

    def test_an_unset_output_is_named_and_the_other_is_written(self):
        self.config(presleep_hr_file=None)
        s, hr = nights(1)
        make_db(self.db, sessions=s, hr=hr)
        code, out, _ = self.run_main("--write")
        self.assertEqual(code, 0)
        self.assertIn("pre-sleep heart-rate file: not configured (set \"presleep_hr_file\" in config.json)", out)
        self.assertTrue(self.sleep.exists())
        self.assertFalse(self.pre.exists())

    def test_an_unwritable_target_is_exit_one_with_one_line(self):
        self.config(sleep_file="blocker/sleep.jsonl")
        (self.st / "blocker").write_text("a file where the directory should be\n")
        s, hr = nights(1)
        make_db(self.db, sessions=s, hr=hr)
        code, out, err = self.run_main("--write")
        self.assertEqual(code, 1)
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertNotIn(str(self.dir), err)
        self.assertNotIn("Traceback", err)


class Cli(Base):
    def test_the_bin_runs_the_same_main(self):
        self.config()
        s, hr = nights(2)
        make_db(self.db, sessions=s, hr=hr)
        env = dict(self.env, PATH=os.environ.get("PATH", ""), HOME=str(self.dir), TZ="UTC")
        r = subprocess.run([sys.executable, "-I", str(CLI)], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry run: two nights of wearable sleep and two nights of pre-sleep heart rate", r.stdout)
        r = subprocess.run([sys.executable, "-I", str(CLI), "--write"], env=env, capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.rows(self.sleep)), 2)


class Words(unittest.TestCase):
    def test_counts_are_spelled(self):
        self.assertEqual([nx.words(n) for n in (0, 1, 2, 13, 20, 21, 99, 100, 365)],
                         ["no", "one", "two", "thirteen", "twenty", "twenty-one", "ninety-nine", "one hundred",
                          "three hundred sixty-five"])
        self.assertEqual(nx.nights_words(1), "one night")
        self.assertEqual(nx.nights_words(0), "no nights")


if __name__ == "__main__":
    unittest.main()
