"""The NOOP export drops demo rows (limitless/mock_guard.py) before anything is counted or written: a demo strap
id, the demo dataset's device name, or a config ``mock_device_patterns`` match. Mixed input says in words that
some demo rows were left out; a database of only demo rows is "no wearable data", never a done export or a live
doctor row; all-real input counts exactly as before.

Synthetic DBs only (tests/noop_fixture.py). UTC stands in for the local zone. Nothing here sends.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import io
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from limitless import doctor, jobs_runner, mock_guard as mg, noop_export as nx  # noqa: E402
from limitless.state_reader import StateReader, config  # noqa: E402
from noop_fixture import RING, hr_before, make_db, stages  # noqa: E402

UTC = timezone.utc
H = 3600
FIRST = date(2030, 1, 1)
NOW = datetime.combine(date(2030, 1, 9), time(12), UTC).timestamp()
LEGACY = "my-whoop"                 # NOOP's legacy strap id: the demo seeders write their dataset under it
DEMO_ID = "demo-band-a"             # the Android demo seeder's id shape (a demo- prefix)
DEMO_ID2 = "band-b-demo"            # the Apple demo seeder's id shape (a -demo suffix)
SIM_ID = "sim-band-c"               # a host's own simulator id, caught only by config mock_device_patterns


def at(d, hh, mm=0):
    return int(datetime.combine(d, time(hh, mm), UTC).timestamp())


def paired(i, kind="liveBLE"):
    return {"id": i, "brand": "Band", "model": "Band", "nickname": None, "peripheralId": None, "sourceKind": kind,
            "capabilities": "hr,sleep", "status": "paired", "addedAt": 0, "lastSeenAt": 0}


def nights(device, n, first=FIRST, bpm=60):
    sessions, hr = [], []
    for i in range(n):
        on = at(first + timedelta(days=i), 23)
        sessions.append((device, on, on + 8 * H, 0.9, stages(on, 7 * H, H)))
        hr += hr_before(device, on, bpm + (i % 3))
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
        self.config()

    def config(self, **kw):
        cfg = {"noop_db": "noop-copy.db", "sleep_file": "sleep.jsonl", "presleep_hr_file": "presleep-hr.jsonl"}
        cfg.update(kw)
        self.cfg_path.write_text(json.dumps({k: v for k, v in cfg.items() if v is not None}))

    def db_with(self, *groups, names=(), devices=None):
        sessions, hr = [], []
        for s, h in groups:
            sessions += s
            hr += h
        devs = devices if devices is not None else [paired(RING, "oura"), paired(DEMO_ID), paired(DEMO_ID2),
                                                    paired(SIM_ID)]
        make_db(self.db, sessions=sessions, hr=hr, devices=devs, names=names)

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = nx.main(list(args), env=self.env, home=self.dir, tz=UTC, out=out, err=err)
        return code, out.getvalue(), err.getvalue()


class Read(Base):
    def test_each_marker_drops_its_sessions_before_counting(self):
        later = FIRST + timedelta(days=10)
        self.db_with(nights(RING, 2), nights(DEMO_ID, 2, later), nights(DEMO_ID2, 1, later + timedelta(days=3)),
                     nights(LEGACY, 1, later + timedelta(days=5)), nights(SIM_ID, 1, later + timedelta(days=7)),
                     names=[(LEGACY, "Band (demo)")])
        got = nx.read(self.db, UTC, cfg={"mock_device_patterns": ["sim-*"]})
        self.assertIsNone(got["reason"])
        self.assertEqual([r["night"] for r in got["sleep"]], ["2030-01-01", "2030-01-02"])
        self.assertEqual([r["night"] for r in got["presleep"]], ["2030-01-01", "2030-01-02"])
        self.assertEqual(got["skipped"]["demo"], 5)

    def test_without_the_config_pattern_a_simulator_id_is_read_as_before(self):
        self.db_with(nights(SIM_ID, 1))
        got = nx.read(self.db, UTC)
        self.assertEqual(len(got["sleep"]), 1)
        self.assertNotIn("demo", got["skipped"])

    def test_a_demo_night_never_beats_a_real_night(self):
        real = [(RING, at(FIRST, 23), at(FIRST, 23) + 6 * H, 0.9, stages(at(FIRST, 23), 5 * H, H))]
        demo = [(DEMO_ID, at(FIRST, 22), at(FIRST, 22) + 9 * H, 0.9, stages(at(FIRST, 22), 8 * H, H))]
        self.db_with((real, hr_before(RING, at(FIRST, 23), 60)), (demo, hr_before(DEMO_ID, at(FIRST, 22), 50)))
        got = nx.read(self.db, UTC)
        self.assertEqual([r["asleep_s"] for r in got["sleep"]], [5 * H])
        self.assertEqual([r["bpm"] for r in got["presleep"]], [60.0])

    def test_only_demo_rows_is_no_wearable_data(self):
        self.db_with(nights(DEMO_ID, 3), nights(LEGACY, 2, FIRST + timedelta(days=5)), names=[(LEGACY, "Band (demo)")])
        got = nx.read(self.db, UTC)
        self.assertEqual((got["sleep"], got["presleep"], got["reason"]), ([], [], mg.ONLY_DEMO))
        self.assertEqual(got["skipped"], {"demo": 5})

    def test_all_real_input_counts_exactly_as_before(self):
        self.db_with(nights(RING, 3), nights(LEGACY, 1, FIRST + timedelta(days=5)), names=[(LEGACY, "Band")])
        got = nx.read(self.db, UTC)
        self.assertEqual(len(got["sleep"]), 4)
        self.assertEqual(got["skipped"], {"not_wearable": 0, "no_asleep_time": 0, "not_a_night": 0, "too_few_hr": 0})

    def test_a_db_without_the_device_table_still_reads(self):
        sessions, hr = nights(RING, 1)
        make_db(self.db, sessions=sessions, hr=hr, drop="device")
        self.assertEqual(len(nx.read(self.db, UTC)["sleep"]), 1)


class Cli(Base):
    def test_mixed_input_says_in_words_that_demo_rows_were_left_out(self):
        self.db_with(nights(RING, 2), nights(DEMO_ID, 3, FIRST + timedelta(days=5)))
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("dry run: two nights of wearable sleep", out)
        self.assertIn("some demo rows were left out (three sessions from a demo or sample device)", out)
        self.assertNotRegex(out, r"\d")

    def test_nothing_is_written_in_a_dry_run(self):
        self.db_with(nights(RING, 2), nights(DEMO_ID, 3, FIRST + timedelta(days=5)))
        self.run_main()
        self.assertFalse(self.sleep.exists())
        self.assertFalse(self.pre.exists())

    def test_only_demo_writes_nothing_even_with_write(self):
        self.db_with(nights(DEMO_ID, 3))
        code, out, err = self.run_main("--write")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.strip(), mg.ONLY_DEMO)
        self.assertFalse(self.sleep.exists())
        self.assertFalse(self.pre.exists())

    def test_write_keeps_only_real_nights(self):
        self.db_with(nights(RING, 2), nights(DEMO_ID, 3, FIRST + timedelta(days=5)))
        code, out, _ = self.run_main("--write")
        self.assertEqual(code, 0)
        rows = [json.loads(ln) for ln in self.sleep.read_text().splitlines()]
        self.assertEqual([r["night"] for r in rows], ["2030-01-01", "2030-01-02"])
        self.assertIn(mg.LEFT_OUT, out)

    def test_the_config_pattern_applies_from_config_json(self):
        self.config(mock_device_patterns=["sim-*"])
        self.db_with(nights(SIM_ID, 2))
        code, out, _ = self.run_main()
        self.assertEqual(out.strip(), mg.ONLY_DEMO)


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class JobAndDoctor(Base):
    def run_job(self):
        (self.st / "runs.jsonl").write_text(json.dumps({"at": iso(NOW - H), "job": "sync", "ok": True,
                                                        "noop": {"copied": True}}) + "\n")
        return jobs_runner.run_once(self.st, NOW, push=None, dry_run=False, env=self.env, home=self.dir, tz=UTC)

    def doc_row(self):
        return doctor.noop_export_row(StateReader(self.st), config(self.env, self.dir), NOW)

    def test_only_demo_is_nothing_to_export_and_never_live(self):
        self.config(noop_export="write")
        self.db_with(nights(DEMO_ID, 3))
        self.run_job()
        self.assertEqual(jobs_runner.load_noop_mark(self.st)["outcome"], jobs_runner.NOOP_NOTHING)
        r = self.doc_row()
        self.assertEqual(r["status"], "stale", r)
        self.assertIn("no wearable data", r["reason"])
        self.assertIn(mg.LEFT_OUT, r["reason"])
        self.assertNotRegex(r["reason"], r"\d")
        self.assertFalse(self.sleep.exists())

    def test_mixed_is_live_and_the_doctor_row_says_demo_rows_were_left_out(self):
        self.config(noop_export="write")
        self.db_with(nights(RING, 2), nights(DEMO_ID, 3, FIRST + timedelta(days=5)))
        self.run_job()
        r = self.doc_row()
        self.assertEqual(r["status"], "live", r)
        self.assertIn(mg.LEFT_OUT, r["reason"])
        self.assertNotRegex(r["reason"], r"\d")

    def test_all_real_doctor_row_is_unchanged(self):
        self.config(noop_export="write")
        self.db_with(nights(RING, 2))
        self.run_job()
        r = self.doc_row()
        self.assertEqual(r["status"], "live", r)
        self.assertNotIn("demo", r["reason"])


if __name__ == "__main__":
    unittest.main()
