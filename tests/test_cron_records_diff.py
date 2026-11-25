"""cron_spec.diff_records and bin/limitless-cron-spec --check: a host's cron job records against the plugin payloads.

The record shape is the public fork kvnloo/hermes-agent, branch up/cron-decision-window-gate-r2: create_job
(cron/jobs.py lines 1872-1921) stores name, script, no_agent, the parsed schedule ({"kind": "interval",
"minutes": n, "display": ...}, lines 787-788), enabled, deliver, and window_class / stale_after_s only when set
(lines 1915-1921, stale_after_s as a float: cron/decision_window.py lines 72-84). The file is {"jobs": [...]}
(cron/jobs.py line 1566); load_jobs also takes a bare list or an id-keyed map (lines 1407-1426). Pause markers
are enabled, state and paused_at (lines 536-543). No Hermes, no network.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hermetic_env import child_env  # noqa: E402
from limitless import cron_spec  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "limitless-cron-spec"
FIXTURE = ROOT / "tests" / "fixtures" / "cron" / "jobs.json"


def host_record(payload, job_id="000000000000"):
    """The record the fork's create_job(**payload) stores (cron/jobs.py lines 1872-1921), synthetic values."""
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


def words(verdicts):
    return {v.name: v.words for v in verdicts}


class DiffRecords(unittest.TestCase):
    def setUp(self):
        self.payloads = cron_spec.payloads()

    def test_records_made_from_the_payloads_are_all_ok(self):
        verdicts = cron_spec.diff_records(in_sync(), self.payloads)
        self.assertEqual([v.name for v in verdicts], [p["name"] for p in self.payloads])
        self.assertEqual({v.words for v in verdicts}, {"ok"})
        self.assertTrue(all(v.ok for v in verdicts))

    def test_a_missing_job_says_missing(self):
        records = [r for r in in_sync() if r["name"] != "limitless-nap"]
        got = words(cron_spec.diff_records(records, self.payloads))
        self.assertEqual(got["limitless-nap"], "missing")
        self.assertEqual(got["limitless-miq"], "ok")

    def test_expiry_alone_differs(self):
        records = in_sync()
        next(r for r in records if r["name"] == "limitless-miq")["stale_after_s"] = 7200.0
        got = words(cron_spec.diff_records(records, self.payloads))
        self.assertEqual(got["limitless-miq"], "differs: expiry")

    def test_an_expiry_the_plugin_dropped_differs(self):
        payloads = [dict(p) for p in self.payloads]
        del payloads[0]["stale_after_s"]
        got = words(cron_spec.diff_records(in_sync(), payloads))
        self.assertEqual(got[payloads[0]["name"]], "differs: expiry")

    def test_window_and_expiry_are_named_in_words(self):
        records = in_sync()
        rec = next(r for r in records if r["name"] == "limitless-miq")
        rec["window_class"], rec["stale_after_s"] = "peak", 3600.0
        got = words(cron_spec.diff_records(records, self.payloads))
        self.assertEqual(got["limitless-miq"], "differs: window and expiry")

    def test_every_field_has_its_word(self):
        records = in_sync()
        rec = next(r for r in records if r["name"] == "limitless-nap")
        rec.update(schedule={"kind": "interval", "minutes": 60, "display": "every 60m"}, script="other.sh",
                   no_agent=False, deliver="telegram")
        del rec["window_class"]
        got = words(cron_spec.diff_records(records, self.payloads))
        self.assertEqual(got["limitless-nap"], "differs: interval, script, agent mode, delivery and window")

    def test_a_paused_record_is_not_ok(self):
        for change in ({"enabled": False}, {"state": "paused"}, {"paused_at": "2000-01-01T00:00:00+00:00"}):
            with self.subTest(change=change):
                records = in_sync()
                next(r for r in records if r["name"] == "limitless-nap").update(change)
                got = cron_spec.diff_records(records, self.payloads)
                self.assertEqual(words(got)["limitless-nap"], "paused on the host")
                self.assertFalse(next(v for v in got if v.name == "limitless-nap").ok)

    def test_a_stored_float_matches_a_whole_number_payload(self):
        records = in_sync()
        for r in records:
            self.assertIsInstance(r["stale_after_s"], float)
        self.assertEqual({v.words for v in cron_spec.diff_records(records, self.payloads)}, {"ok"})

    def test_window_case_and_spaces_are_how_the_host_reads_them(self):
        records = in_sync()
        next(r for r in records if r["name"] == "limitless-miq")["window_class"] = " Wind_Down "
        self.assertEqual(words(cron_spec.diff_records(records, self.payloads))["limitless-miq"], "ok")

    def test_an_old_limitless_job_is_not_a_plugin_job_any_more(self):
        records = in_sync() + [host_record(dict(self.payloads[0], name="limitless-gone", script="limitless-gone.sh"))]
        verdicts = cron_spec.diff_records(records, self.payloads)
        self.assertEqual(verdicts[-1].name, "limitless-gone")
        self.assertEqual(verdicts[-1].words, "not a plugin job any more")
        self.assertFalse(verdicts[-1].ok)

    def test_other_host_jobs_are_left_alone(self):
        other = host_record(dict(self.payloads[0], name="daily digest", script="digest.sh"))
        verdicts = cron_spec.diff_records(in_sync() + [other], self.payloads)
        self.assertNotIn("daily digest", words(verdicts))

    def test_two_host_jobs_with_one_name(self):
        records = in_sync()
        records.append(copy.deepcopy(records[0]))
        got = words(cron_spec.diff_records(records, self.payloads))
        self.assertEqual(got[self.payloads[0]["name"]], "more than one host job with this name")

    def test_malformed_records_are_unreadable_never_a_raise(self):
        bad_values = ({"schedule": "every 5m"}, {"schedule": None}, {"stale_after_s": "an hour"},
                      {"stale_after_s": True}, {"stale_after_s": -1}, {"stale_after_s": float("nan")},
                      {"window_class": 3}, {"script": ["a"]}, {"deliver": {"x": 1}})
        for change in bad_values:
            with self.subTest(change=change):
                records = in_sync()
                next(r for r in records if r["name"] == "limitless-nap").update(change)
                got = words(cron_spec.diff_records(records, self.payloads))
                self.assertTrue(got["limitless-nap"].startswith("unreadable"), got["limitless-nap"])
        junk = in_sync() + ["text", None, 7, [], {"name": 5}, {"no": "name"}]
        verdicts = cron_spec.diff_records(junk, self.payloads)
        unreadable = [v for v in verdicts if v.words == "unreadable"]
        self.assertEqual(len(unreadable), 6)
        self.assertEqual({v.words for v in verdicts if v not in unreadable}, {"ok"})

    def test_a_record_list_that_is_not_a_list_never_raises(self):
        for records in (None, 5, "x", {"jobs": 1}):
            with self.subTest(records=records):
                verdicts = cron_spec.diff_records(records, self.payloads)
                self.assertEqual({v.words for v in verdicts}, {"missing"} | ({"unreadable"} if records else set()))

    def test_the_fixture(self):
        records = cron_spec.records_in(json.loads(FIXTURE.read_text(encoding="utf-8")))
        got = cron_spec.diff_records(records, self.payloads)
        lines = cron_spec.check_lines(got)
        self.assertIn("limitless-miq: differs: window and expiry", lines)
        self.assertIn("limitless-old_reminder: not a plugin job any more", lines)
        self.assertIn("limitless-nap: unreadable: interval and expiry", lines)
        self.assertIn("limitless-wake_brief: missing", lines)
        self.assertIn("record four: unreadable", lines)
        self.assertFalse(any("someone else" in line for line in lines))
        self.assertEqual(len(lines), len(self.payloads) + 2)

    def test_pure(self):
        records, payloads = in_sync(), cron_spec.payloads()
        before = copy.deepcopy((records, payloads))
        cron_spec.diff_records(records, payloads)
        self.assertEqual((records, payloads), before)


class RecordsIn(unittest.TestCase):
    def test_the_shapes_the_host_loads(self):
        rec = in_sync()
        self.assertEqual(cron_spec.records_in({"jobs": rec, "updated_at": "x"}), rec)
        self.assertEqual(cron_spec.records_in(rec), rec)
        keyed = cron_spec.records_in({"jobs": {"k1": {"name": "limitless-miq"}, "k2": "junk"}})
        self.assertEqual(keyed, [{"name": "limitless-miq", "id": "k1"}])
        self.assertEqual(cron_spec.records_in({"updated_at": "x"}), [])   # data.get("jobs", []), line 1408

    def test_other_shapes_are_unreadable(self):
        for data in ("x", 5, None, {"jobs": 5}, {"jobs": "x"}):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    cron_spec.records_in(data)


class CheckCli(unittest.TestCase):
    def run_cli(self, home, *args):
        keep = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")}
        return subprocess.run([sys.executable, "-I", str(BIN), *args], env=child_env(dict(keep, HOME=str(home))),
                              capture_output=True, text=True, timeout=60, cwd=str(home))

    def listing(self, root):
        return sorted((str(p.relative_to(root)), p.stat().st_mtime_ns, p.stat().st_size, p.stat().st_mode)
                      for p in root.rglob("*"))

    def test_in_sync_file_exits_zero_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            jobs = home / ".hermes" / "cron" / "jobs.json"
            jobs.parent.mkdir(parents=True)
            jobs.write_text(json.dumps({"jobs": in_sync(), "updated_at": "x"}), encoding="utf-8")
            jobs.chmod(0o400)
            before = self.listing(home)
            r = self.run_cli(home, "--check", str(jobs))
            after = self.listing(home)
            jobs.chmod(0o600)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), [f"{p['name']}: ok" for p in cron_spec.payloads()])
        self.assertEqual(before, after)

    def test_drift_exits_one_with_one_line_per_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            r = self.run_cli(home, "--check", str(FIXTURE))
        self.assertEqual(r.returncode, 1, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines, cron_spec.check_lines(cron_spec.diff_records(
            cron_spec.records_in(json.loads(FIXTURE.read_text(encoding="utf-8"))), cron_spec.payloads())))
        self.assertIn("limitless-miq: differs: window and expiry", lines)

    def test_usage_and_unreadable_files_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "bad.json").write_text("{not json", encoding="utf-8")
            (home / "shape.json").write_text('{"jobs": 3}', encoding="utf-8")
            (home / "bytes.json").write_bytes(b"\xff\xfe\x00")
            cases = (("--check",), ("--check", "a", "b"), ("--check", str(home / "absent.json")),
                     ("--check", str(home / "bad.json")), ("--check", str(home / "shape.json")),
                     ("--check", str(home / "bytes.json")), ("--check", str(home)))
            results = [(args, self.run_cli(home, *args)) for args in cases]
        for args, r in results:
            with self.subTest(args=args):
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(r.stdout, "")
                self.assertTrue(r.stderr.strip())
                self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
