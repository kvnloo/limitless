"""bin/limitless-once-key <job>: the event key for one job, for senders that cannot import Python.

Synthetic data only. Times are relative to the clock the CLI reads; only differences matter.
Nothing sends: the CLI only reads, and a fake `hermes` on PATH would record any call.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, jobs_runner  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-once-key"
H = 3600.0
UTC = timezone.utc


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        bindir = self.home / "bin"
        bindir.mkdir()
        hermes = bindir / "hermes"
        hermes.write_text("#!/bin/sh\necho called >> \"$HOME/hermes-calls\"\nexit 0\n")
        hermes.chmod(0o755)
        self.attention = self.home / "attention.json"
        self.env = {"HOME": str(self.home), "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
                    "LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.home / "no-config.json"),
                    "LIMITLESS_GLIDE_ATTENTION": str(self.attention), "TZ": "UTC"}
        self.now = time.time()

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args, env=None):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(env or self.env),
                              capture_output=True, text=True, timeout=30)

    def awake_after_night(self, off):
        write_rows(self.st / "sleepmode.jsonl", [{"at": iso(off - 8 * H), "on": True}, {"at": iso(off), "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": iso(self.now - 30), "ok": True}))
        write_rows(self.st / "unlocks.jsonl", [{"at": iso(self.now - 60)}])

    def wind_down_rows(self, at):
        """A wake two hours before the wind-down, so the night date is the wake's (UTC) date."""
        write_rows(self.st / "events.jsonl", [{"event": "wake", "at": iso(at - 2 * H)},
                                              {"event": "wind_down", "at": iso(at)}])
        return f"miq:{datetime.fromtimestamp(at - 2 * H, UTC).date().isoformat()}"

    def wind_down(self, at):
        key = self.wind_down_rows(at)
        self.attention.write_text(json.dumps({"block": None, "resume": {"saved": int(at)}}))
        return key

    def nap(self, off):
        write_rows(self.st / "sleepmode.jsonl", [{"at": iso(off - 0.5 * H), "on": True}, {"at": iso(off), "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": iso(self.now - 30), "ok": True}))

    def in_process_key(self, job):
        return jobs_runner.event_key(self.st, time.time(), job=job, env=self.env, home=self.home, tz=UTC)


class PrintsTheKey(Base):
    def test_wake_brief_key(self):
        off = int(self.now - 0.2 * H)
        self.awake_after_night(off)
        r = self.cli("wake_brief")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, f"wake_brief:{off}\n", ""))

    def test_miq_key_is_the_wind_down_night(self):
        key = self.wind_down(int(self.now - 120))
        r = self.cli("miq")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, f"{key}\n", ""))
        self.assertEqual(r.stdout.strip(), self.in_process_key("miq"))

    def test_nap_key_is_the_nap_end_time(self):
        off = int(self.now - 300)
        self.nap(off)
        r = self.cli("nap")
        self.assertEqual((r.returncode, r.stdout), (0, f"nap:{off}\n"))
        self.assertEqual(r.stdout.strip(), self.in_process_key("nap"))

    def test_every_job_matches_event_key(self):
        self.awake_after_night(int(self.now - 1.5 * H))
        self.wind_down(int(self.now - 120))
        for job in jobs.SPECS:
            r = self.cli(job)
            want = self.in_process_key(job)
            self.assertEqual(r.stdout.strip() or None, want, job)
            self.assertEqual(r.returncode, 0 if want else 3, job)

    def test_a_job_held_by_its_window_still_has_its_events_key(self):
        # No Glide wind-down window: run_once holds MIQ, but the event is the same, so is its key.
        key = self.wind_down_rows(int(self.now - 120))
        r = self.cli("miq")
        self.assertEqual((r.returncode, r.stdout), (0, f"{key}\n"))


class NoKey(Base):
    def assert_no_key(self, r):
        self.assertEqual((r.returncode, r.stdout), (3, ""), r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_no_trigger_is_exit_3_and_prints_nothing(self):
        for job in jobs.SPECS:
            self.assert_no_key(self.cli(job))

    def test_missing_state_dir(self):
        self.assert_no_key(self.cli("miq", env=dict(self.env, LIMITLESS_STATE=str(self.home / "nowhere"))))

    def test_state_path_is_a_file(self):
        f = self.home / "a-file"
        f.write_text("not a dir")
        self.assert_no_key(self.cli("wake_brief", env=dict(self.env, LIMITLESS_STATE=str(f))))

    def test_broken_state_files(self):
        for name in ("sleepmode.jsonl", "events.jsonl", "screen-events.jsonl", "unlocks.jsonl", "jobs-sent.jsonl"):
            (self.st / name).write_text("{not json\n[1, 2\n\"x\"\n")
        (self.st / "sleepmode-poll.json").write_text("{not json")
        (self.st / "habit.json").write_text("[]")
        self.attention.write_text("{not json")
        for job in jobs.SPECS:
            self.assert_no_key(self.cli(job))

    def test_broken_config(self):
        cfg = self.home / "config.json"
        cfg.write_text("{not json")
        env = dict(self.env, LIMITLESS_CONFIG=str(cfg))
        env.pop("LIMITLESS_STATE")
        self.assert_no_key(self.cli("nap", env=env))


class Usage(Base):
    def test_unknown_job_is_exit_2_with_a_usage_line(self):
        r = self.cli("not_a_job")
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertTrue(r.stderr.startswith("usage: limitless-once-key <job>"), r.stderr)
        self.assertEqual(len(r.stderr.splitlines()), 1)
        for job in jobs.SPECS:
            self.assertIn(job, r.stderr)

    def test_no_job_or_two_jobs_is_exit_2(self):
        for args in ((), ("miq", "nap"), ("--send",)):
            r = self.cli(*args)
            self.assertEqual((r.returncode, r.stdout), (2, ""), args)
            self.assertTrue(r.stderr.startswith("usage: limitless-once-key <job>"), args)

    def test_help_is_exit_0(self):
        r = self.cli("--help")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.startswith("usage: limitless-once-key <job>"))


class NightFlag(Base):
    """`miq --night`: tonight's key even with no wind-down event, for a sender with its own cue."""

    def wake(self, at):
        write_rows(self.st / "events.jsonl", [{"event": "wake", "at": iso(at)}])
        return f"miq:{datetime.fromtimestamp(at, UTC).date().isoformat()}"

    def test_no_wind_down_still_prints_tonights_key(self):
        key = self.wake(self.now - 2 * H)
        r = self.cli("miq", "--night")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, f"{key}\n", ""))
        self.assertEqual(r.stdout.strip(), jobs_runner.night_key(self.st, time.time(), env=self.env,
                                                                  home=self.home, tz=UTC))

    def test_without_night_no_wind_down_is_still_exit_3(self):
        self.wake(self.now - 2 * H)
        self.assertEqual((self.cli("miq").returncode, self.cli("miq").stdout), (3, ""))

    def test_with_a_wind_down_tonight_it_equals_the_event_key(self):
        self.wind_down(int(self.now - 120))
        plain, night = self.cli("miq"), self.cli("miq", "--night")
        self.assertEqual((night.returncode, night.stdout), (0, plain.stdout))
        self.assertEqual(night.stdout.strip(), self.in_process_key("miq"))

    def test_flag_may_come_first(self):
        key = self.wake(self.now - 2 * H)
        self.assertEqual(self.cli("--night", "miq").stdout, f"{key}\n")

    def test_no_state_still_prints_a_night_key(self):
        before = datetime.fromtimestamp(time.time(), UTC).date().isoformat()
        r = self.cli("miq", "--night", env=dict(self.env, LIMITLESS_STATE=str(self.home / "nowhere")))
        after = datetime.fromtimestamp(time.time(), UTC).date().isoformat()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(r.stdout, {f"miq:{before}\n", f"miq:{after}\n"})

    def test_night_is_only_for_night_jobs(self):
        for job in sorted(set(jobs.SPECS) - set(jobs_runner.NIGHT_JOBS)):
            r = self.cli(job, "--night")
            self.assertEqual((r.returncode, r.stdout), (2, ""), job)
            self.assertTrue(r.stderr.startswith("usage: limitless-once-key"), job)

    def test_usage_names_the_flag(self):
        self.assertIn("--night", self.cli("--help").stdout)


class ReadOnly(Base):
    def snapshot(self):
        return sorted((str(p.relative_to(self.home)), p.stat().st_mtime_ns, p.stat().st_size)
                      for p in self.home.rglob("*"))

    def test_never_writes_or_sends(self):
        self.awake_after_night(int(self.now - 0.2 * H))
        self.wind_down(int(self.now - 120))
        write_rows(self.st / "jobs-sent.jsonl", [])
        before = self.snapshot()
        time.sleep(0.05)
        for job in list(jobs.SPECS) + ["not_a_job"]:
            self.cli(job)
        self.cli("miq", "--night")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.home / "hermes-calls").exists())
        self.assertFalse((self.home / ".local").exists())


if __name__ == "__main__":
    unittest.main()
