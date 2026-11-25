"""The doctor's `host job records` row: do the host's cron job records (config host_jobs_file, the host's
cron/jobs.json) match this plugin's payloads, as bin/limitless-cron-spec --check would say?

Synthetic temp files only, in the shapes of tests/fixtures/cron/jobs.json. The row opens the file once as text and
never writes or locks it; Hermes is never imported or run.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import copy
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermetic_env import child_env

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import cron_spec, doctor  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "cron" / "jobs.json"
NOW = 1894708800.0   # the fixture clock; the row reads no clock at all

ROW = "host job records"
OFF = "no host jobs file set (config host_jobs_file)"
NOT_THERE = "the host jobs file is not there"
NOT_JOBS = "the host jobs file cannot be read as a jobs file"
OK = "every sending job's host record matches"
ABSENT = "some jobs are not on the host: "
DIFFER = "some host jobs differ from this plugin's: "
RETIRED = "a host job the plugin no longer has"
NO_NAME = "a host job record with no name to read"
EVERY_JOB = "wake brief, nap, miq, habit checkin, week review, break nudge, outage recap and sender confirm"


def host_record(payload, job_id="000000000000"):
    """The record the host's create_job(**payload) stores, in tests/fixtures/cron/jobs.json's shape."""
    minutes = int(re.fullmatch(r"every (\d+)m", payload["schedule"]).group(1))
    schedule = {"kind": "interval", "minutes": minutes, "display": f"every {minutes}m"}
    rec = {"id": job_id, "name": payload["name"], "prompt": payload["prompt"], "skills": [], "skill": None,
           "model": None, "provider": None, "base_url": None, "script": payload["script"],
           "no_agent": payload["no_agent"], "monitor_script": None, "monitor_url": None, "monitor_state": None,
           "context_from": None, "schedule": schedule, "schedule_display": schedule["display"],
           "repeat": {"times": None, "completed": 0}, "enabled": True, "state": "scheduled", "paused_at": None,
           "paused_reason": None, "created_at": "2000-01-01T00:00:00+00:00", "next_run_at": None,
           "last_run_at": None, "last_status": None, "last_error": None, "last_delivery_error": None,
           "last_delivery_unverified": None, "last_failure": None, "failure_streak": 0,
           "deliver": payload["deliver"], "origin": None, "enabled_toolsets": None, "workdir": None}
    for key in ("window_class", "stale_after_s"):
        if payload.get(key) is not None:
            rec[key] = float(payload[key]) if key == "stale_after_s" else payload[key]
    return rec


def in_sync():
    return [host_record(p, f"{i:012d}") for i, p in enumerate(cron_spec.payloads())]


def other_job():
    """Someone else's host job, as in the fixture: the row leaves it alone."""
    return {"id": "cccccccccccc", "name": "someone else's job", "prompt": "Summarise the synthetic feed.",
            "script": None, "no_agent": False, "schedule": {"kind": "interval", "minutes": 60,
                                                             "display": "every 60m"},
            "enabled": True, "state": "scheduled", "paused_at": None, "deliver": "local"}


def by_name(records, job):
    return next(r for r in records if r["name"] == f"limitless-{job}")


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.file = self.root / "cron" / "jobs.json"
        p = mock.patch.dict(os.environ, {}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def write(self, records, wrap=True):
        self.file.parent.mkdir(exist_ok=True)
        data = {"jobs": records, "updated_at": "2000-01-01T00:00:00+00:00"} if wrap else records
        self.file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def row(self, cfg=None):
        return doctor.host_jobs_row({"host_jobs_file": str(self.file)} if cfg is None else cfg)

    def check(self, r, status, reason):
        self.assertEqual((r["name"], r["kind"], r["status"], r["reason"]), (ROW, "source", status, reason))
        self.assertEqual(doctor.text([r]), f"{ROW}: {status}: {reason}")
        self.assertNotRegex(r["reason"], r"\d")
        self.assertNotIn(str(self.root), r["reason"])
        self.assertNotIn("/", r["reason"])
        self.assertNotIn("limitless-", r["reason"])


class Off(Case):
    def test_key_not_set_is_off(self):
        self.check(self.row({}), doctor.OFF, OFF)

    def test_blank_or_not_a_string_is_off(self):
        for v in ("", "   ", None, 7, ["x"]):
            with self.subTest(v=v):
                self.check(self.row({"host_jobs_file": v}), doctor.OFF, OFF)

    def test_not_a_mapping_is_off(self):
        self.check(doctor.host_jobs_row("not a dict"), doctor.OFF, OFF)


class MissingFile(Case):
    def test_the_file_is_not_there(self):
        self.check(self.row(), doctor.MISSING, NOT_THERE)

    def test_a_tilde_path_is_expanded(self):
        self.check(self.row({"host_jobs_file": "~/no-such-dir/jobs.json"}), doctor.MISSING, NOT_THERE)

    def test_files_that_are_not_a_jobs_file(self):
        cases = {"not json": b"{not json", "a number": b"5", "jobs is a number": b'{"jobs": 3}',
                 "a string": b'"jobs"', "not text": b"\xff\xfe\x00", "empty": b""}
        for label, data in cases.items():
            with self.subTest(label):
                self.file.parent.mkdir(exist_ok=True)
                self.file.write_bytes(data)
                self.check(self.row(), doctor.MISSING, NOT_JOBS)

    def test_a_dir_where_the_file_should_be(self):
        self.file.mkdir(parents=True)
        self.check(self.row(), doctor.MISSING, NOT_JOBS)

    def test_a_file_it_may_not_read(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root reads any file")
        self.write(in_sync())
        self.file.chmod(0)
        self.addCleanup(self.file.chmod, 0o600)
        self.check(self.row(), doctor.MISSING, NOT_JOBS)


class MissingJobs(Case):
    def test_an_empty_jobs_file_names_every_sending_job(self):
        self.write([])
        self.check(self.row(), doctor.MISSING, ABSENT + EVERY_JOB)

    def test_a_file_with_only_other_jobs(self):
        self.write([other_job()])
        self.check(self.row(), doctor.MISSING, ABSENT + EVERY_JOB)

    def test_two_missing_jobs_in_all_specs_order(self):
        self.write([r for r in in_sync() if r["name"] not in ("limitless-week_review", "limitless-nap")])
        self.check(self.row(), doctor.MISSING, ABSENT + "nap and week review")

    def test_missing_and_stale_together_say_both_and_stay_missing(self):
        records = [r for r in in_sync() if r["name"] != "limitless-nap"]
        by_name(records, "miq")["stale_after_s"] = 7200.0
        self.write(records)
        self.check(self.row(), doctor.MISSING, ABSENT + "nap; " + DIFFER + "miq")


class Stale(Case):
    def test_an_expiry_that_differs(self):
        records = in_sync()
        by_name(records, "miq")["stale_after_s"] = 7200.0
        self.write(records)
        self.check(self.row(), doctor.STALE, DIFFER + "miq")

    def test_a_job_paused_on_the_host(self):
        for change in ({"enabled": False}, {"state": "paused"}, {"paused_at": "2000-01-01T00:00:00+00:00"}):
            with self.subTest(change=change):
                records = in_sync()
                by_name(records, "habit_checkin").update(change)
                self.write(records)
                self.check(self.row(), doctor.STALE, DIFFER + "habit checkin")

    def test_an_unreadable_record(self):
        records = in_sync()
        by_name(records, "nap")["schedule"] = "every 5m"   # stored unparsed, as in the fixture
        self.write(records)
        self.check(self.row(), doctor.STALE, DIFFER + "nap")

    def test_more_than_one_host_job_with_a_name(self):
        records = in_sync()
        records.append(copy.deepcopy(by_name(records, "week_review")))
        self.write(records)
        self.check(self.row(), doctor.STALE, DIFFER + "week review")

    def test_a_host_job_the_plugin_no_longer_has(self):
        gone = host_record(dict(cron_spec.payloads()[0], name="limitless-old_reminder",
                                script="limitless-old_reminder.sh"))
        self.write(in_sync() + [gone])
        self.check(self.row(), doctor.STALE, RETIRED)

    def test_a_record_with_no_name(self):
        self.write(in_sync() + ["not a record"])
        self.check(self.row(), doctor.STALE, NO_NAME)

    def test_several_kinds_in_order(self):
        records = in_sync()
        by_name(records, "break_nudge")["window_class"] = "peak"
        by_name(records, "wake_brief")["enabled"] = False
        by_name(records, "nap")["stale_after_s"] = "an hour"
        records.append(host_record(dict(cron_spec.payloads()[0], name="limitless-gone", script="gone.sh")))
        self.write(records)
        self.check(self.row(), doctor.STALE, DIFFER + "wake brief, nap and break nudge; " + RETIRED)

    def test_the_fixture(self):
        r = doctor.host_jobs_row({"host_jobs_file": str(FIXTURE)})
        self.check(r, doctor.MISSING, ABSENT + "wake brief, habit checkin, week review, break nudge, outage recap "
                                               "and sender confirm; " + DIFFER + "nap and miq; " + RETIRED + "; " +
                   NO_NAME)


class Ok(Case):
    def test_every_record_matches(self):
        self.write(in_sync())
        self.check(self.row(), doctor.LIVE, OK)

    def test_other_jobs_are_left_alone(self):
        self.write([other_job()] + in_sync())
        self.check(self.row(), doctor.LIVE, OK)

    def test_the_other_shapes_the_host_loads(self):
        self.write(in_sync(), wrap=False)                                   # a bare list
        self.check(self.row(), doctor.LIVE, OK)
        self.write({r["id"]: r for r in in_sync()})                          # an id-keyed map
        self.check(self.row(), doctor.LIVE, OK)

    def test_the_row_agrees_with_check(self):
        """Live exactly when bin/limitless-cron-spec --check exits zero, for the same file."""
        bin_ = ROOT / "bin" / "limitless-cron-spec"
        records = in_sync()
        cases = (("in sync", records), ("paused", [dict(r, enabled=False) if r["name"] == "limitless-miq" else r
                                                  for r in records]))
        for label, recs in cases:
            with self.subTest(label):
                self.write(recs)
                got = subprocess.run([sys.executable, "-I", str(bin_), "--check", str(self.file)],
                                     capture_output=True, text=True, timeout=60, env=child_env())
                self.assertEqual(got.returncode == 0, self.row()["status"] == doctor.LIVE, got.stdout)


class ReadOnly(Case):
    def test_opened_once_for_reading_and_never_written(self):
        self.write(in_sync())
        self.file.chmod(0o400)
        self.addCleanup(self.file.chmod, 0o600)
        before = (self.file.stat().st_mtime_ns, stat.S_IMODE(self.file.stat().st_mode), self.file.read_bytes())
        real = open
        calls = []

        def spy(file, mode="r", *a, **k):
            calls.append((str(file), mode))
            return real(file, mode, *a, **k)

        def boom(*a, **k):
            raise AssertionError("the row must not do this")

        with mock.patch("builtins.open", spy), mock.patch.object(subprocess, "run", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(os, "replace", boom), \
                mock.patch.object(os, "rename", boom), mock.patch.object(os, "unlink", boom), \
                mock.patch.object(os, "chmod", boom), mock.patch.object(os, "system", boom):
            self.check(self.row(), doctor.LIVE, OK)
        self.assertEqual(calls, [(str(self.file), "r")])
        after = (self.file.stat().st_mtime_ns, stat.S_IMODE(self.file.stat().st_mode), self.file.read_bytes())
        self.assertEqual(after, before)

    def test_no_lock_and_no_hermes(self):
        self.write(in_sync())
        import fcntl
        with mock.patch.object(fcntl, "flock", side_effect=AssertionError("no lock")), \
                mock.patch.object(fcntl, "lockf", side_effect=AssertionError("no lock")):
            self.check(self.row(), doctor.LIVE, OK)
        self.assertFalse([m for m in sys.modules if m == "hermes_cli" or m.startswith(("hermes_cli.", "cron."))])

    def test_it_reuses_diff_records(self):
        self.write(in_sync())
        with mock.patch.object(cron_spec, "diff_records", wraps=cron_spec.diff_records) as spy:
            self.row()
        spy.assert_called_once()


class InTheReport(Case):
    def test_it_comes_right_after_the_host_job_scripts_row(self):
        st = self.root / "state"
        st.mkdir()
        rows = doctor.report({"state": str(st)}, NOW)
        names = [r["name"] for r in rows]
        at = names.index(doctor.HOST_SCRIPTS_ROW)
        self.assertEqual(names[at + 1], ROW)
        self.assertEqual(names[at + 2], doctor.DESKTOP_AW_ROW)
        self.assertEqual((rows[at + 1]["kind"], rows[at + 1]["status"], rows[at + 1]["reason"]),
                         ("source", doctor.OFF, OFF))

    def test_the_report_reads_the_config_key(self):
        st = self.root / "state"
        st.mkdir()
        self.write(in_sync())
        rows = doctor.report({"state": str(st), "host_jobs_file": str(self.file)}, NOW)
        r = next(r for r in rows if r["name"] == ROW)
        self.assertEqual((r["status"], r["reason"]), (doctor.LIVE, OK))


if __name__ == "__main__":
    unittest.main()
