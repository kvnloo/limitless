"""limitless-jobs --job <name> (run_once(..., only=<name>)) and the limitless-<job>.sh scripts cron_spec writes.

One job's pass: the same gates, marks and dry-run default as the full pass, for that job alone. Synthetic state in
a temp dir only: a nap (so "Back from nap" delivers) and one sync row with the FIT import in dry_run mode (so a full
--send pass writes two marks, jobs-sent.jsonl and fit-ingest.json). kevin-push is a stub on PATH that records calls.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import cron_spec, jobs, jobs_runner  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-jobs"
SPEC_CLI = ROOT / "bin" / "limitless-cron-spec"
H = 3600.0
NAMES = [s.name for s in cron_spec.all_specs()]
CLOCK_TIME = re.compile(r"(?i)\b\d{1,2}(:\d{2}|\s*(am|pm)\b|h\d{2})")   # 7:30, 7am, 19h00: a digit-led clock time

STUB_PUSH = """#!{py}
import json, os, sys
with open(os.environ["STUB_PUSH_CALLS"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
print("kevin-push: telegram")
"""


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def listing(root):
    """Every file under ``root`` with its size and content, so any write shows up."""
    return sorted((str(p.relative_to(root)), p.read_bytes()) for p in Path(root).rglob("*") if p.is_file())


class State(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        (self.st / "drop").mkdir()
        now = time.time()
        write_rows(self.st / "sleepmode.jsonl", [{"at": iso(now - 12 * H), "on": True}, {"at": iso(now - 3 * H), "on": False},
                                                 {"at": iso(now - 1 * H), "on": True}, {"at": iso(now - 0.1 * H), "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": iso(now - 30), "ok": True}))
        write_rows(self.st / "unlocks.jsonl", [{"at": iso(now - 60)}])
        write_rows(self.st / "runs.jsonl", [{"at": iso(now - 0.5 * H), "job": "sync", "ok": True}])
        self.cfg = self.home / "config.json"
        self.cfg.write_text(json.dumps({"fit_ingest": "dry_run", "fit_drop_dir": "drop", "rides_file": "rides.jsonl"}))
        bindir = self.home / "bin"
        bindir.mkdir()
        stub = bindir / "kevin-push"
        stub.write_text(STUB_PUSH.format(py=sys.executable))
        stub.chmod(0o755)
        self.calls = self.home / "calls.jsonl"
        self.env = {"HOME": str(self.home), "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
                    "LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.cfg),
                    "STUB_PUSH_CALLS": str(self.calls)}

    def run_cli(self, *args, **env):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(dict(self.env, **env)),
                              capture_output=True, text=True, timeout=60)

    def push_calls(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def changed(self, before):
        """The state files a run added or changed."""
        b = dict(before)
        return sorted(name for name, data in listing(self.st) if b.get(name) != data)


class SingleJobCli(State):
    def test_the_full_pass_writes_both_marks(self):
        """The fixture itself: without --job, --send writes the nap's sent log and the FIT import's mark."""
        before = listing(self.st)
        r = self.run_cli("--send")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.changed(before), ["fit-ingest.json", "jobs-sent.jsonl"], r.stdout)
        self.assertGreater(len(r.stdout.splitlines()), 1)

    def test_one_job_send_changes_only_its_mark(self):
        before = listing(self.st)
        r = self.run_cli("--job", "nap", "--send")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.changed(before), ["jobs-sent.jsonl"], r.stdout)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 1, r.stdout)
        self.assertTrue(lines[0].startswith("Back from nap: deliver"), r.stdout)
        self.assertEqual(len(self.push_calls()), 1)

    def test_a_job_that_sends_nothing_changes_only_its_mark(self):
        before = listing(self.st)
        r = self.run_cli("--job", "fit_ingest", "--send")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("fit_ingest", cron_spec.SENDS_NOTHING)
        self.assertEqual(self.changed(before), ["fit-ingest.json"], r.stdout)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 1, r.stdout)
        self.assertTrue(lines[0].startswith("FIT import: "), r.stdout)
        self.assertEqual(self.push_calls(), [])

    def test_dry_run_never_calls_the_sender_and_prints_the_full_pass_line(self):
        full = self.run_cli()
        before = listing(self.st)
        one = self.run_cli("--job", "nap")
        self.assertEqual(one.returncode, 0, one.stderr)
        self.assertEqual(self.push_calls(), [])
        self.assertEqual(self.changed(before), [])
        nap = [ln for ln in full.stdout.splitlines() if ln.startswith("Back from nap: ")]
        self.assertEqual(one.stdout.splitlines(), nap)

    def test_every_named_job_runs_alone(self):
        before = listing(self.st)
        for name in NAMES:
            with self.subTest(job=name):
                r = self.run_cli("--job", name)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertLessEqual(len(r.stdout.splitlines()), 1, r.stdout)
        self.assertEqual(self.push_calls(), [])
        self.assertEqual(self.changed(before), [])

    def test_unknown_name_is_usage_and_writes_nothing(self):
        before = listing(self.st)
        for args in (("--job", "nope", "--send"), ("--job",), ("--job", "--send")):
            with self.subTest(args=args):
                r = self.run_cli(*args)
                self.assertEqual(r.returncode, 2, r.stdout)
                self.assertEqual(r.stdout, "")
                self.assertIn("usage", r.stderr)
                for name in NAMES:
                    self.assertIn(name, r.stderr)
        self.assertEqual(self.changed(before), [])
        self.assertEqual(self.push_calls(), [])


class OnlySeam(State):
    def once(self, **kw):
        return jobs_runner.run_once(self.st, time.time(), push=lambda *a, **k: "telegram", dry_run=False,
                                    env=self.env, home=self.home, **kw)

    def test_only_returns_that_job_row(self):
        rows = self.once(only=jobs.NAP.name)
        self.assertEqual([r["job"] for r in rows], [jobs.NAP.send_title])

    def test_only_an_unknown_name_is_a_value_error_and_writes_nothing(self):
        before = listing(self.st)
        with self.assertRaises(ValueError):
            self.once(only="nope")
        self.assertEqual(self.changed(before), [])

    def test_names_are_the_cron_spec_jobs(self):
        self.assertEqual(list(jobs_runner.JOB_NAMES), NAMES)


class ScriptBody(unittest.TestCase):
    def test_every_script_is_posix_sh_names_its_job_and_has_no_clock_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            for spec in cron_spec.all_specs():
                with self.subTest(job=spec.name):
                    body = cron_spec.script_body(spec)
                    path = Path(tmp) / f"limitless-{spec.name}.sh"
                    path.write_text(body)
                    r = subprocess.run(["sh", "-n", str(path)], env=child_env({"PATH": os.environ.get("PATH", "")}),
                                       capture_output=True, text=True, timeout=30)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertTrue(body.startswith("#!/bin/sh\n"))
                    self.assertIsNone(CLOCK_TIME.search(body), body)
                    self.assertIn(f" --job {spec.name} --send", body)
                    self.assertIn("LIMITLESS_PLUGIN_DIR", body)
                    self.assertNotRegex(body, r"/Users/|/home/|~/")

    def test_pure(self):
        self.assertEqual(cron_spec.script_body(jobs.MIQ), cron_spec.script_body(jobs.MIQ))

    def test_a_name_that_is_not_a_plain_word_is_refused(self):
        from types import SimpleNamespace
        with self.assertRaises(ValueError):
            cron_spec.script_body(SimpleNamespace(name="nap; reboot", send_title="x"))


class ScriptRuns(State):
    def script(self, name):
        p = self.home / f"limitless-{name}.sh"
        p.write_text(cron_spec.script_body(jobs.SPECS[name]))
        p.chmod(0o700)
        return p

    def test_the_script_runs_one_job_send_through_the_plugin_dir(self):
        before = listing(self.st)
        r = subprocess.run(["sh", str(self.script("nap"))],
                           env=child_env(dict(self.env, LIMITLESS_PLUGIN_DIR=str(ROOT))),
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.splitlines()), 1, r.stdout)
        self.assertTrue(r.stdout.startswith("Back from nap: deliver"), r.stdout)
        self.assertEqual(len(self.push_calls()), 1)
        self.assertEqual(self.changed(before), ["jobs-sent.jsonl"])

    def test_without_the_plugin_dir_it_runs_nothing(self):
        before = listing(self.st)
        r = subprocess.run(["sh", str(self.script("nap"))], env=child_env(self.env),
                           capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("LIMITLESS_PLUGIN_DIR", r.stderr)
        self.assertEqual(self.push_calls(), [])
        self.assertEqual(self.changed(before), [])


class ScriptsFlag(unittest.TestCase):
    def run_cli(self, home, *args):
        keep = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")}
        return subprocess.run([sys.executable, "-I", str(SPEC_CLI), *args], env=child_env(dict(keep, HOME=str(home))),
                              capture_output=True, text=True, timeout=60, cwd=str(home))

    def test_writes_one_0700_script_per_payload_into_the_given_dir_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            out = home / "scripts"
            out.mkdir()
            r = self.run_cli(home, "--scripts", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
            payloads = cron_spec.payloads()
            self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(p["script"] for p in payloads))
            self.assertEqual(sorted(str(p.relative_to(home)) for p in home.rglob("*")),
                             sorted(["scripts"] + [f"scripts/{p['script']}" for p in payloads]))
            by_name = {f"limitless-{s.name}.sh": s for s in cron_spec.all_specs()}
            for f in out.iterdir():
                with self.subTest(script=f.name):
                    self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o700)
                    self.assertEqual(f.read_text(), cron_spec.script_body(by_name[f.name]))
            again = self.run_cli(home, "--scripts", str(out))
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(p["script"] for p in payloads))

    def test_a_missing_dir_is_usage_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            for args in (("--scripts", str(home / "nope")), ("--scripts",)):
                with self.subTest(args=args):
                    r = self.run_cli(home, *args)
                    self.assertEqual(r.returncode, 2, r.stdout)
                    self.assertIn("usage", r.stderr)
            self.assertEqual(list(home.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
