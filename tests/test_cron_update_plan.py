"""cron_spec.update_plan and bin/limitless-cron-spec --plan: the host calls that would bring the records in step.

The plan names calls on the public fork kvnloo/hermes-agent, branch up/cron-decision-window-gate-r2 (read at
a910662): create_job (cron/jobs.py lines 1779-1925; the record it stores, lines 1872-1921) and
update_job(job_id, updates) (lines 2096-2151), which merges ``updates`` over the record (line 2107) after the
create-time normalizers (lines 1738-1755, decision_window.py lines 58-84). An update without ``enabled`` /
``state`` never resumes a paused job: a schedule change leaves a paused record's next run alone (line 2072) and so
does the missing-next-run fill (lines 2081-2085). The plan never makes a call; nothing here imports Hermes.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import ast
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hermetic_env import child_env  # noqa: E402
from limitless import cron_spec  # noqa: E402
from test_cron_records_diff import host_record, in_sync  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "limitless-cron-spec"
FIXTURE = ROOT / "tests" / "fixtures" / "cron" / "jobs-plan.json"
PAUSE = {"enabled": False, "state": "paused", "paused_at": "2000-01-02T00:00:00+00:00",
         "paused_reason": "synthetic pause"}
LIFECYCLE = {"enabled", "state", "paused_at", "paused_reason", "next_run_at"}
RETIRED_WHY = "not a plugin job any more; remove it by hand if wanted"


def fixture_records():
    return cron_spec.records_in(json.loads(FIXTURE.read_text(encoding="utf-8")))


def by_job(plan):
    out = {}
    for step in plan:
        out.setdefault(step["job"], []).append(step)
    return out


def applied(records, plan):
    """``records`` with each update_job step merged over the record whose id it names (update_job line 2107)
    and each create_job step's payload stored as create_job would store it."""
    out = copy.deepcopy(records)
    for step in plan:
        if step["call"] == "update_job":
            rec = next(r for r in out if isinstance(r, dict) and r.get("id") == step["job_id"])
            rec.update(step["updates"])
        elif step["call"] == "create_job":
            out.append(host_record(step["kwargs"], "f" * 12))
    return out


def change(name, **fields):
    records = in_sync()
    next(r for r in records if r["name"] == name).update(fields)
    return records


class UpdatePlan(unittest.TestCase):
    def setUp(self):
        self.payloads = cron_spec.payloads()

    def plan(self, records, payloads=None):
        return cron_spec.update_plan(records, self.payloads if payloads is None else payloads)

    def test_records_in_step_plan_nothing(self):
        self.assertEqual(self.plan(in_sync()), [])

    def test_a_missing_job_is_a_create_job_with_its_payload(self):
        records = [r for r in in_sync() if r["name"] != "limitless-nap"]
        plan = self.plan(records)
        nap = next(p for p in self.payloads if p["name"] == "limitless-nap")
        self.assertEqual(plan, [{"job": "limitless-nap", "call": "create_job", "kwargs": nap}])
        plan[0]["kwargs"]["window_class"] = "peak"
        self.assertEqual(cron_spec.payloads(), self.payloads)   # a copy, never the payload itself

    def test_window_differs_updates_the_window_only(self):
        records = change("limitless-nap", window_class="peak")
        rec = next(r for r in records if r["name"] == "limitless-nap")
        self.assertEqual(self.plan(records), [{"job": "limitless-nap", "call": "update_job", "job_id": rec["id"],
                                               "updates": {"window_class": "anytime"}}])

    def test_expiry_differs_updates_the_expiry_as_stored_float(self):
        plan = self.plan(change("limitless-miq", stale_after_s=3600.0))
        self.assertEqual([s["updates"] for s in plan], [{"stale_after_s": 10800.0}])
        self.assertIsInstance(plan[0]["updates"]["stale_after_s"], float)   # decision_window.py lines 72-84

    def test_interval_differs_updates_the_parsed_schedule(self):
        plan = self.plan(change("limitless-miq", schedule={"kind": "interval", "minutes": 15,
                                                           "display": "every 15m"}))
        # the dict parse_schedule stores for "every 5m" (cron/jobs.py lines 787-788, stored at line 1887)
        self.assertEqual([s["updates"] for s in plan],
                         [{"schedule": {"kind": "interval", "minutes": 5, "display": "every 5m"}}])

    def test_every_field_in_its_stored_form(self):
        records = change("limitless-nap", schedule={"kind": "interval", "minutes": 60, "display": "every 60m"},
                         script="other.sh", no_agent=False, deliver="telegram", window_class=None,
                         stale_after_s=None)
        self.assertEqual(self.plan(records)[0]["updates"], {
            "schedule": {"kind": "interval", "minutes": 5, "display": "every 5m"}, "script": "limitless-nap.sh",
            "no_agent": True, "deliver": "local", "window_class": "anytime", "stale_after_s": 3600.0})

    def test_a_field_the_plugin_dropped_is_cleared(self):
        payloads = [dict(p) for p in self.payloads]
        del payloads[0]["stale_after_s"]
        plan = self.plan(in_sync(), payloads)
        self.assertEqual([(s["job"], s["updates"]) for s in plan], [(payloads[0]["name"], {"stale_after_s": None})])

    def test_host_normalizing_alone_plans_nothing(self):
        self.assertEqual(self.plan(change("limitless-miq", window_class=" Wind_Down ")), [])

    def test_paused_only_plans_nothing(self):
        for marker in ({"enabled": False}, {"state": "paused"}, {"paused_at": "2000-01-02T00:00:00+00:00"}, PAUSE):
            with self.subTest(marker=marker):
                self.assertEqual(self.plan(change("limitless-nap", **marker)), [])

    def test_paused_and_differs_updates_only_the_differing_field(self):
        records = change("limitless-nap", stale_after_s=7200.0, **PAUSE)
        plan = self.plan(records)
        self.assertEqual([s["updates"] for s in plan], [{"stale_after_s": 3600.0}])
        self.assertFalse(LIFECYCLE & set(plan[0]["updates"]))
        verdicts = {v.name: v.words for v in cron_spec.diff_records(applied(records, plan), self.payloads)}
        self.assertEqual(verdicts["limitless-nap"], "paused on the host")   # still paused after the update

    def test_no_update_ever_touches_the_pause(self):
        records = fixture_records()
        for step in self.plan(records):
            if step["call"] == "update_job":
                with self.subTest(job=step["job"]):
                    self.assertFalse(LIFECYCLE & set(step["updates"]), step)

    def test_an_unreadable_record_is_left_to_the_operator(self):
        plan = self.plan(change("limitless-nap", stale_after_s="an hour"))
        self.assertEqual(plan, [{"job": "limitless-nap", "call": "none",
                                 "why": "unreadable: expiry; fix the record by hand, then plan again"}])

    def test_a_record_with_no_name_is_left_to_the_operator(self):
        plan = self.plan(in_sync() + ["text", {"no": "name"}])
        self.assertEqual([(s["job"], s["call"]) for s in plan], [("record nine", "none"), ("record ten", "none")])
        self.assertTrue(all(s["why"].startswith("unreadable") for s in plan))

    def test_a_record_with_no_id_cannot_be_updated(self):
        records = change("limitless-nap", window_class="peak")
        del next(r for r in records if r["name"] == "limitless-nap")["id"]
        self.assertEqual(self.plan(records), [{"job": "limitless-nap", "call": "none",
                                               "why": "differs, but the host record has no id to update by"}])

    def test_two_host_jobs_with_one_name_are_left_to_the_operator(self):
        records = in_sync()
        records.append(copy.deepcopy(records[0]))
        self.assertEqual(self.plan(records), [{
            "job": self.payloads[0]["name"], "call": "none",
            "why": "more than one host job with this name; keep one by hand, then plan again"}])

    def test_a_retired_plugin_job_is_never_deleted(self):
        old = host_record(dict(self.payloads[0], name="limitless-gone", script="limitless-gone.sh"), "e" * 12)
        self.assertEqual(self.plan(in_sync() + [old]), [{"job": "limitless-gone", "call": "none", "why": RETIRED_WHY}])

    def test_other_host_jobs_are_left_alone(self):
        other = host_record(dict(self.payloads[0], name="daily digest", script="digest.sh"), "d" * 12)
        other["stale_after_s"] = 60.0
        self.assertEqual(self.plan(in_sync() + [other]), [])

    def test_the_fixture(self):
        records = fixture_records()
        self.assertEqual(self.plan(records), [
            {"job": "limitless-wake_brief", "call": "create_job", "kwargs": self.payloads[0]},
            {"job": "limitless-nap", "call": "update_job", "job_id": "a00000000001",
             "updates": {"window_class": "anytime"}},
            {"job": "limitless-miq", "call": "update_job", "job_id": "a00000000002",
             "updates": {"stale_after_s": 10800.0}},
            {"job": "limitless-habit_checkin", "call": "update_job", "job_id": "a00000000003",
             "updates": {"schedule": {"kind": "interval", "minutes": 5, "display": "every 5m"}}},
            {"job": "limitless-break_nudge", "call": "update_job", "job_id": "a00000000005",
             "updates": {"stale_after_s": 21600.0}},
            {"job": "limitless-outage_recap", "call": "none",
             "why": "unreadable: interval and expiry; fix the record by hand, then plan again"},
            {"job": "limitless-sender_confirm", "call": "none",
             "why": "more than one host job with this name; keep one by hand, then plan again"},
            {"job": "limitless-old_reminder", "call": "none", "why": RETIRED_WHY},
            {"job": "record eleven", "call": "none", "why": "unreadable: no name to read; fix it by hand"},
        ])
        self.assertEqual(self.payloads[0]["name"], "limitless-wake_brief")

    def test_each_planned_call_makes_its_job_ok(self):
        cases = {"fixture": fixture_records(), "missing": [r for r in in_sync() if r["name"] != "limitless-miq"],
                 "window": change("limitless-nap", window_class="peak"),
                 "expiry": change("limitless-miq", stale_after_s=1.0),
                 "interval": change("limitless-miq", schedule={"kind": "interval", "minutes": 1, "display": "x"}),
                 "paused and differs": change("limitless-nap", window_class="peak", **PAUSE)}
        for label, records in cases.items():
            plan = self.plan(records)
            after = {v.name: v.words for v in cron_spec.diff_records(applied(records, plan), self.payloads)}
            for step in plan:
                if step["call"] == "none":
                    continue
                with self.subTest(case=label, job=step["job"]):
                    paused = any(cron_spec._paused(r) for r in records
                                 if isinstance(r, dict) and r.get("name") == step["job"])
                    self.assertEqual(after[step["job"]], "paused on the host" if paused else "ok")

    def test_only_the_three_calls(self):
        calls = {s["call"] for s in self.plan(fixture_records())}
        self.assertEqual(calls, {"create_job", "update_job", "none"})

    def test_pure_and_never_raises(self):
        records, payloads = fixture_records(), cron_spec.payloads()
        before = copy.deepcopy((records, payloads))
        cron_spec.update_plan(records, payloads)
        self.assertEqual((records, payloads), before)
        for junk in (None, 5, "x", {"jobs": 1}, [None, 7, []]):
            with self.subTest(records=junk):
                plan = cron_spec.update_plan(junk, payloads)
                self.assertEqual([s["job"] for s in plan if s["call"] == "create_job"], [p["name"] for p in payloads])


class PlanCli(unittest.TestCase):
    def run_cli(self, home, *args):
        keep = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")}
        return subprocess.run([sys.executable, "-I", str(BIN), *args], env=child_env(dict(keep, HOME=str(home))),
                              capture_output=True, text=True, timeout=60, cwd=str(home))

    def listing(self, root):
        return sorted((str(p.relative_to(root)), p.stat().st_mtime_ns, p.stat().st_size, p.stat().st_mode)
                      for p in root.rglob("*"))

    def test_in_step_prints_an_empty_list_exits_zero_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            jobs = home / ".hermes" / "cron" / "jobs.json"
            jobs.parent.mkdir(parents=True)
            records = in_sync()
            records[1].update(PAUSE)   # paused only: nothing to plan
            jobs.write_text(json.dumps({"jobs": records}), encoding="utf-8")
            jobs.chmod(0o400)
            before = self.listing(home)
            r = self.run_cli(home, "--plan", str(jobs))
            after = self.listing(home)
            jobs.chmod(0o600)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "[]\n")
        self.assertEqual(before, after)

    def test_drift_prints_the_plan_as_json_and_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self.run_cli(Path(tmp), "--plan", str(FIXTURE))
        self.assertEqual(r.returncode, 1, r.stderr)
        want = cron_spec.update_plan(fixture_records(), cron_spec.payloads())
        self.assertEqual(r.stdout, json.dumps(want, indent=1, sort_keys=True) + "\n")
        self.assertEqual(json.loads(r.stdout), want)

    def test_usage_and_unreadable_files_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "bad.json").write_text("{not json", encoding="utf-8")
            (home / "shape.json").write_text('{"jobs": 3}', encoding="utf-8")
            cases = (("--plan",), ("--plan", "a", "b"), ("--plan", str(home / "absent.json")),
                     ("--plan", str(home / "bad.json")), ("--plan", str(home / "shape.json")), ("--plan", str(home)))
            results = [(args, self.run_cli(home, *args)) for args in cases]
        for args, r in results:
            with self.subTest(args=args):
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(r.stdout, "")
                self.assertTrue(r.stderr.strip())
                self.assertNotIn("Traceback", r.stderr)

    def test_never_imports_hermes(self):
        allowed = {"json", "os", "sys", "tempfile", "pathlib", "limitless", "math", "re", "shlex", "typing"}
        for path in (BIN, ROOT / "limitless" / "cron_spec.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            with self.subTest(path=path.name):
                self.assertLessEqual(names, allowed)

    def test_the_doc_names_the_flag(self):
        doc = (ROOT / "docs" / "decision-window.md").read_text(encoding="utf-8")
        self.assertTrue("limitless-cron-spec --plan" in doc, "docs/decision-window.md never names --plan")
        self.assertTrue("--plan" in BIN.read_text(encoding="utf-8").split('"""')[1], "the usage text lacks --plan")


if __name__ == "__main__":
    unittest.main()
