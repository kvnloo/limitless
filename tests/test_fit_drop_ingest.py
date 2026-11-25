"""CAROL FIT files dropped in one folder reach the rides file by themselves: the FIT import as one more ingest of
limitless-jobs, once per new sync row, as config ``fit_ingest`` says (off, dry_run, write) for the folder config
``fit_drop_dir`` names; limitless-doctor's "job FIT import" row and the schedule card say so in words.

Every FIT file here is SYNTHETIC, built by the tiny writer in tests/test_fit_ride.py from made-up values; synthetic
runs.jsonl rows only. Nothing here sends: the in-process passes get a fake push that only records, and the CLI test
puts a fake kevin-push on KEVIN_PUSH_BIN that only records its calls.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import doctor, fit_ingest_job, fit_ride, jobs, jobs_runner, schedule_cards, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_fit_ride import ride_file  # noqa: E402  (the synthetic FIT writer)

UTC = timezone.utc
H = 3600
NOW = datetime(2030, 1, 20, 9, 0, tzinfo=UTC).timestamp()
JOB = "FIT import"
CLI = ROOT / "bin" / "limitless-jobs"
EPOCH_KEYS = {"row_at", "ran_at", "read_to", "added_at"}

FAKE_PUSH = """#!{py}
import os, sys
with open(os.environ["FAKE_PUSH_CALLS"], "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
print("kevin-push: telegram")
"""


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync(t):
    return {"at": iso(t), "job": "sync", "ok": True}


def start(i):
    """A synthetic ride start, one day apart per index."""
    return iso(datetime(2030, 1, 1, 7, 0, tzinfo=UTC).timestamp() + i * 24 * H)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.drop_dir = self.st / "drop"
        self.drop_dir.mkdir()
        self.rides = self.st / "rides.jsonl"
        self.mark = self.st / fit_ingest_job.MARK
        self.cfg_path = self.dir / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg_path), "LIMITLESS_STATE": str(self.st)}
        self.pushed = []
        self.runs(sync(NOW - H))
        self.mtime = NOW - 30 * 24 * H

    def push(self, *a, **kw):
        self.pushed.append((a, kw))
        return "telegram"

    def config(self, **kw):
        cfg = {"rides_file": "rides.jsonl", "fit_drop_dir": "drop"}
        cfg.update(kw)
        self.cfg = {k: v for k, v in cfg.items() if v is not None}
        self.cfg_path.write_text(json.dumps(self.cfg))

    def runs(self, *rows):
        (self.st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def drop(self, name, data=None, folder=None, **kw):
        p = (folder or self.drop_dir) / name
        p.write_bytes(ride_file(**kw) if data is None else data)
        self.mtime += 60
        os.utime(p, (self.mtime, self.mtime))
        return p

    def once(self, now=NOW, dry_run=False, ingest=False):
        return jobs_runner.run_once(self.st, now, push=self.push, dry_run=dry_run, env=self.env, home=self.dir,
                                    tz=UTC, ingest=ingest)

    def row(self, rows):
        got = [r for r in rows if r["job"] == JOB]
        self.assertEqual(len(got), 1, rows)
        return got[0]

    def no_row(self, rows):
        self.assertEqual([r for r in rows if r["job"] == JOB], [])

    def ride_rows(self):
        if not self.rides.exists():
            return []
        return [json.loads(ln) for ln in self.rides.read_text().splitlines() if ln.strip()]

    def load_mark(self):
        return json.loads(self.mark.read_text())

    def doc(self, now=NOW):
        return doctor.fit_import_row(StateReader(self.st), self.cfg, now, env=self.env)

    def snapshot(self):
        return {p.name: (p.read_bytes(), p.stat().st_mtime) for p in sorted(self.drop_dir.iterdir())}


class Off(Base):
    def test_off_is_the_default_and_does_nothing(self):
        self.config()
        self.drop("a.fit", start=start(1))
        self.no_row(self.once())
        self.assertFalse(self.mark.exists())
        self.assertFalse(self.rides.exists())

    def test_anything_but_dry_run_or_write_is_off(self):
        self.drop("a.fit", start=start(1))
        for v in ("off", "OFF", False, None, "sometimes", 1, True):
            self.config(fit_ingest=v)
            self.no_row(self.once())
            self.assertFalse(self.mark.exists(), v)
            self.assertFalse(self.rides.exists(), v)

    def test_mode_reads_its_own_key(self):
        self.assertEqual(jobs.fit_mode({}), jobs.FIT_OFF)
        self.assertEqual(jobs.fit_mode({"fit_ingest": " Dry_Run "}), jobs.FIT_DRY_RUN)
        self.assertEqual(jobs.fit_mode({"fit_ingest": "write"}), jobs.FIT_WRITE)
        self.assertEqual(jobs.fit_mode({"apps_ingest": "write"}), jobs.FIT_OFF)

    def test_off_doctor_row(self):
        self.config()
        r = self.doc()
        self.assertEqual((r["name"], r["status"]), ("job FIT import", doctor.OFF))
        self.assertIn("off (config fit_ingest)", r["reason"])


class DryRun(Base):
    def test_dry_run_writes_no_ride_and_says_what_it_would_add(self):
        self.config(fit_ingest="dry_run")
        self.drop("a.fit", start=start(1))
        self.drop("b.FIT", start=start(2))
        before = self.snapshot()
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.RUN)
        self.assertIn("would add two rides", r["reason"])
        self.assertFalse(self.rides.exists())
        self.assertEqual(self.snapshot(), before)
        m = self.load_mark()
        self.assertEqual(m["mode"], "dry_run")
        self.assertIn("would add two rides", m["said"])
        self.assertNotIn("read_to", m, "a dry run never moves the place a write pass reads from")

    def test_a_dry_run_of_limitless_jobs_reads_nothing(self):
        self.config(fit_ingest="write")
        self.drop("a.fit", start=start(1))
        r = self.row(self.once(dry_run=True))
        self.assertIn("dry run of limitless-jobs: not run", r["reason"])
        self.assertFalse(self.mark.exists())
        self.assertFalse(self.rides.exists())

    def test_the_ingest_pass_runs_it(self):
        self.config(fit_ingest="write")
        self.drop("a.fit", start=start(1))
        r = self.row(self.once(dry_run=True, ingest=True))
        self.assertIn("added one ride", r["reason"])
        self.assertEqual(len(self.ride_rows()), 1)
        self.assertEqual(self.pushed, [])


class Write(Base):
    def test_write_appends_once_and_a_second_pass_adds_nothing(self):
        self.config(fit_ingest="write")
        self.drop("a.fit", start=start(1))
        self.drop("b.fit", start=start(2))
        before = self.snapshot()
        r = self.row(self.once())
        self.assertIn("added two rides", r["reason"])
        rows = self.ride_rows()
        self.assertEqual([x["start"] for x in rows], [start(1), start(2)])
        self.assertTrue(all(x["source"] == "carol-fit" for x in rows))
        # the same sync row again: dropped, nothing read
        r = self.row(self.once(now=NOW + 60))
        self.assertEqual(r["action"], jobs.DROP)
        self.assertIn("already ran after this sync", r["reason"])
        # a new sync row: a second pass, nothing new
        self.runs(sync(NOW - H), sync(NOW + 120))
        r = self.row(self.once(now=NOW + 180))
        self.assertEqual(r["action"], jobs.RUN)
        self.assertIn("nothing new", r["reason"])
        self.assertEqual(self.ride_rows(), rows)
        self.assertEqual(self.snapshot(), before, "a source file is never moved, renamed, deleted or rewritten")
        self.assertEqual(self.pushed, [])

    def test_a_file_imported_by_hand_is_not_added_again(self):
        self.config(fit_ingest="write")
        p = self.drop("a.fit", start=start(1))
        fit_ride.run([p], self.rides, write=True)
        r = self.row(self.once())
        self.assertIn("nothing new", r["reason"])
        self.assertIn("one file already in the rides file", r["reason"])
        self.assertEqual(len(self.ride_rows()), 1)

    def test_a_new_file_after_a_pass_is_added_on_the_next(self):
        self.config(fit_ingest="write")
        self.drop("a.fit", start=start(1))
        self.once()
        self.drop("b.fit", start=start(2))
        self.runs(sync(NOW - H), sync(NOW + 120))
        r = self.row(self.once(now=NOW + 180))
        self.assertIn("added one ride", r["reason"])
        self.assertEqual([x["start"] for x in self.ride_rows()], [start(1), start(2)])

    def test_a_non_bike_file_is_reported_not_imported(self):
        self.config(fit_ingest="write")
        self.drop("bike.fit", start=start(1))
        self.drop("run.fit", start=start(2), sport=1)
        r = self.row(self.once())
        self.assertIn("added one ride", r["reason"])
        self.assertIn("skipped one file: not a bike ride", r["reason"])
        self.assertEqual([x["start"] for x in self.ride_rows()], [start(1)])

    def test_no_rides_file_set_adds_nothing_and_says_why(self):
        self.config(fit_ingest="write", rides_file=None)
        self.drop("a.fit", start=start(1))
        r = self.row(self.once())
        self.assertIn("added no rides: no rides file set (config rides_file)", r["reason"])
        self.assertNotIn("read_to", self.load_mark(), "a pass that could not write reads the same files again")

    def test_only_fit_files_directly_in_the_folder(self):
        self.config(fit_ingest="write")
        sub = self.drop_dir / "sub"
        sub.mkdir()
        self.drop("deep.fit", folder=sub, start=start(1))
        self.drop("notes.txt", start=start(2))
        self.drop(".hidden.fit", start=start(3))
        outside = self.dir / "outside"
        outside.mkdir()
        target = self.drop("elsewhere.fit", folder=outside, start=start(4))
        os.symlink(target, self.drop_dir / "link.fit")
        os.symlink(outside, self.drop_dir / "linked-dir.fit")
        self.drop("top.fit", start=start(5))
        r = self.row(self.once())
        self.assertIn("added one ride", r["reason"])
        self.assertEqual([x["start"] for x in self.ride_rows()], [start(5)])

    def test_at_most_a_cap_per_pass_oldest_first_and_the_rest_next_pass(self):
        self.config(fit_ingest="write")
        cap = fit_ingest_job.FILES_PER_PASS
        for i in range(cap + 2):
            self.drop(f"r{i}.fit", start=start(i))
        r = self.row(self.once())
        self.assertIn("more files wait for the next pass", r["reason"])
        got = [x["start"] for x in self.ride_rows()]
        self.assertEqual(got, [start(i) for i in range(cap)], "oldest modification time first")
        self.runs(sync(NOW - H), sync(NOW + 120))
        r = self.row(self.once(now=NOW + 180))
        self.assertIn("added two rides", r["reason"])
        self.assertNotIn("wait", r["reason"])
        self.assertEqual([x["start"] for x in self.ride_rows()], [start(i) for i in range(cap + 2)])

    def test_files_sharing_one_modification_time_are_not_split_by_the_cap(self):
        self.config(fit_ingest="write")
        cap = fit_ingest_job.FILES_PER_PASS
        for i in range(cap + 1):
            p = self.drop(f"r{i:02d}.fit", start=start(i))
            if i >= cap - 1:                       # the files either side of the cap share one time
                os.utime(p, (NOW - 2 * H, NOW - 2 * H))
        self.once()
        self.runs(sync(NOW - H), sync(NOW + 120))
        self.once(now=NOW + 180)
        self.assertEqual(sorted(x["start"] for x in self.ride_rows()), [start(i) for i in range(cap + 1)])


class Folder(Base):
    def test_folder_missing(self):
        self.config(fit_ingest="write", fit_drop_dir="not-there")
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.NOT_TRIGGERED)
        self.assertIn("the drop folder does not exist", r["reason"])
        self.assertFalse(self.mark.exists())
        d = self.doc()
        self.assertEqual(d["status"], doctor.MISSING)
        self.assertIn("the drop folder does not exist", d["reason"])
        self.assertNotIn("not-there", d["reason"])

    def test_folder_not_set(self):
        self.config(fit_ingest="dry_run", fit_drop_dir=None)
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.NOT_TRIGGERED)
        self.assertIn("no drop folder set (config fit_drop_dir)", r["reason"])
        self.assertEqual(self.doc()["status"], doctor.STALE)

    def test_a_relative_folder_is_in_the_state_dir_and_an_absolute_one_is_kept(self):
        self.assertEqual(fit_ingest_job.drop_dir(self.st, {"fit_drop_dir": "drop"}), self.st / "drop")
        elsewhere = self.dir / "elsewhere"
        self.assertEqual(fit_ingest_job.drop_dir(self.st, {"fit_drop_dir": str(elsewhere)}), elsewhere)
        self.assertIsNone(fit_ingest_job.drop_dir(self.st, {"fit_drop_dir": "  "}))


class Mark(Base):
    def test_mark_is_private_words_and_epochs_only(self):
        self.config(fit_ingest="write")
        self.drop("ride-secret-name.fit", start=start(1))
        self.drop("run.fit", start=start(2), sport=1)
        self.once()
        self.assertEqual(stat.S_IMODE(self.mark.stat().st_mode), 0o600)
        m = self.load_mark()
        for k in EPOCH_KEYS & set(m):
            self.assertIsInstance(m[k], (int, float), k)
        rest = {k: v for k, v in m.items() if k not in EPOCH_KEYS}
        text = json.dumps(rest)
        self.assertNotRegex(text, r"\d", text)
        for w in ("ride-secret-name", "run.fit", ".fit", str(self.dir), "drop"):
            self.assertNotIn(w, self.mark.read_text())
        self.assertEqual(m["mode"], "write")
        self.assertIn("added one ride", m["said"])
        self.assertIn("skipped one file: not a bike ride", m["said"])

    def test_doctor_row_after_a_pass_is_live_with_the_last_pass_words(self):
        self.config(fit_ingest="dry_run")
        self.drop("a.fit", start=start(1))
        self.once()
        r = self.doc(now=NOW + 2 * H)
        self.assertEqual((r["name"], r["status"]), ("job FIT import", doctor.LIVE))
        self.assertTrue(r["reason"].startswith("dry run: "), r["reason"])
        self.assertIn("would add one ride", r["reason"])
        self.assertNotRegex(r["reason"], r"\d")

    def test_doctor_row_waits_for_a_new_sync(self):
        self.config(fit_ingest="write")
        r = self.doc()
        self.assertEqual(r["status"], doctor.STALE)
        self.assertIn(f"({jobs.INGEST_RUNS} runs it)", r["reason"])

    def test_the_doctor_report_has_the_row(self):
        self.config(fit_ingest="write")
        rows = doctor.report(self.cfg, NOW)
        self.assertEqual(len([r for r in rows if r["name"] == "job FIT import"]), 1)


class NeverSends(Base):
    def test_the_cli_ingest_and_send_passes_never_call_kevin_push(self):
        self.config(fit_ingest="write")
        self.drop("a.fit", start=start(1))
        bindir = self.dir / "bin"
        bindir.mkdir()
        fake = bindir / "kevin-push"
        fake.write_text(FAKE_PUSH.format(py=sys.executable))
        fake.chmod(0o755)
        calls = self.dir / "calls.txt"
        self.runs(sync(time.time() - 60))           # the CLI reads its own clock: a sync row just before it
        env = dict(self.env, HOME=str(self.dir), KEVIN_PUSH_BIN=str(fake), FAKE_PUSH_CALLS=str(calls),
                   LIMITLESS_BRIEF_BIN=str(fake), PATH=f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
        for args in (["--ingest", "--confirm"], ["--send"]):
            r = subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(env), capture_output=True,
                               text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(f"{JOB}: ", r.stdout)
        self.assertFalse(calls.exists(), "kevin-push was called")
        self.assertEqual(len(self.ride_rows()), 1)


class Card(Base):
    def test_one_card_on_the_sync_event_that_sends_nothing(self):
        c = schedule_cards.fit_ingest_card()
        self.assertEqual((c["id"], c["trigger"], c["sender"], c["budget"]), ("fit_ingest", "sync", "local", 0))
        self.assertEqual(c["words"]["runs"], jobs.INGEST_RUNS)
        self.assertNotRegex(c["description"], r"\d")
        self.assertIn(c, schedule_cards.cards(fit=True))
        self.assertNotIn(c, schedule_cards.cards())

    def test_the_schedule_tool_adds_it_when_on(self):
        self.config(fit_ingest="dry_run")
        ids = [c["id"] for c in tools.schedule(StateReader(self.st), NOW, env=self.env, home=self.dir)
               ["value"]["cards"]]
        self.assertEqual(ids.count("fit_ingest"), 1)
        self.config()
        ids = [c["id"] for c in tools.schedule(StateReader(self.st), NOW, env=self.env, home=self.dir)
               ["value"]["cards"]]
        self.assertNotIn("fit_ingest", ids)


class Docs(unittest.TestCase):
    def test_the_fit_doc_has_a_drop_folder_section(self):
        text = (ROOT / "docs" / "carol-fit-import.md").read_text(encoding="utf-8")
        self.assertIn("## Drop folder", text)
        sec = text.split("## Drop folder", 1)[1]
        for w in ("fit_drop_dir", "fit_ingest", "dry_run", "write", "limitless-jobs --ingest", "job FIT import",
                  fit_ingest_job.MARK, "never moved"):
            self.assertIn(w, sec)

    def test_the_doctor_doc_has_the_row(self):
        text = (ROOT / "docs" / "doctor.md").read_text(encoding="utf-8")
        self.assertEqual(len([ln for ln in text.splitlines() if ln.startswith("| `job FIT import`")]), 1)


if __name__ == "__main__":
    unittest.main()
