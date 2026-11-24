"""cron_spec.job_spec and bin/limitless-cron-spec: the Hermes cron job each plugin job would be, dry run only.

The host side is the public fork kvnloo/hermes-agent, branch up/cron-decision-window-gate-r2 (a9106628). Neither
its `hermes cron create` CLI (hermes_cli/subcommands/cron.py lines 52-133) nor its cronjob tool schema
(tools/cronjob_tools.py) takes window_class or stale_after_s; only the Python job API does (cron/jobs.py lines
1779-1810, create_job(..., window_class=None, stale_after_s=None)). So a payload here is create_job's keyword
arguments. The acceptance rules below are copied from the fork, so this test needs no Hermes and no network.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hermetic_env import child_env  # noqa: E402
from limitless import cron_spec, jobs  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "limitless-cron-spec"

# The host's WindowClass values: cron/decision_window.py lines 30-34.
HERMES_WINDOW_CLASSES = frozenset({"peak", "trough", "anytime", "wind_down"})

# create_job's keyword parameters a payload may use: cron/jobs.py lines 1779-1810 (a subset of them).
CREATE_JOB_KWARGS = frozenset({"prompt", "schedule", "name", "deliver", "script", "no_agent",
                               "window_class", "stale_after_s"})


def fork_normalize_window_class(value):
    """Copy of cron/decision_window.py lines 58-69 (normalize_window_class)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str):
        clean = value.strip().lower()
        if clean in HERMES_WINDOW_CLASSES:
            return clean
    raise ValueError(f"window_class must be one of {sorted(HERMES_WINDOW_CLASSES)}, not {value!r}.")


def fork_normalize_stale_after_s(value):
    """Copy of cron/decision_window.py lines 72-84 (normalize_stale_after_s)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError("stale_after_s must be a number of seconds, not a boolean.")
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"stale_after_s must be a number of seconds, not {value!r}.") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"stale_after_s must be a positive number of seconds, not {value!r}.")
    return seconds


def fork_validate_window_knobs(schedule, window_class, stale_after_s):
    """Copy of cron/decision_window.py lines 87-95 (validate_window_knobs); cron/jobs.py line 1852 calls it in
    create_job, lines 2142-2144 in update_job."""
    kind = (schedule or {}).get("kind")
    for name, value in (("window_class", window_class), ("stale_after_s", stale_after_s)):
        if value is not None and kind not in {"cron", "interval"}:
            raise ValueError(f"{name} needs a recurring schedule (cron or interval); kind is {kind!r}.")


def fork_parse_every(schedule):
    """The part of cron/jobs.py parse_schedule (lines 791-811) an "every <duration>" string takes: an interval of
    parse_duration minutes (lines 681-690; m, h or d); anything else here is not an interval."""
    m = re.match(r"^every\s+(\d*)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)$",
                 schedule.strip().lower())
    if not m:
        return {"kind": None}
    return {"kind": "interval", "minutes": int(m.group(1) or 1) * {"m": 1, "h": 60, "d": 1440}[m.group(2)[0]]}


def fork_script_is_plain_filename(script):
    """cron/jobs_invariants.py lines 70-78 refuse a script with whitespace (a command line) that is no file, and
    cron/job_args.py lines 416-440 want a path relative to the scripts dir (no "/" or "~" first, no traversal)."""
    return bool(script) and not any(c.isspace() for c in script) and not script.startswith(("/", "~")) \
        and ".." not in script and "/" not in script


class JobSpec(unittest.TestCase):
    def test_every_sending_job_gets_a_payload_the_fork_accepts(self):
        payloads = [cron_spec.job_spec(s) for s in cron_spec.all_specs()]
        sending = [p for p in payloads if p]
        self.assertGreaterEqual(len(sending), 8)
        for p in sending:
            with self.subTest(job=p["name"]):
                self.assertLessEqual(set(p), CREATE_JOB_KWARGS)
                schedule = fork_parse_every(p["schedule"])
                self.assertEqual(schedule["kind"], "interval")
                wc = fork_normalize_window_class(p["window_class"])
                self.assertIn(wc, HERMES_WINDOW_CLASSES)
                stale = fork_normalize_stale_after_s(p.get("stale_after_s"))
                fork_validate_window_knobs(schedule, wc, stale)
                self.assertTrue(p["no_agent"])
                self.assertTrue(fork_script_is_plain_filename(p["script"]), p["script"])
                self.assertEqual(p["deliver"], "local")   # the plugin's own send gate sends; Hermes never does

    def test_payload_carries_to_cron_fields(self):
        for spec in cron_spec.all_specs():
            p = cron_spec.job_spec(spec)
            if not p:
                continue
            with self.subTest(job=spec.name):
                f = jobs.to_cron_fields(spec)
                self.assertEqual({k: p[k] for k in f}, f)
                self.assertEqual("stale_after_s" in p, "stale_after_s" in f)

    def test_named_jobs(self):
        p = cron_spec.job_spec(jobs.MIQ)
        self.assertEqual(p["name"], "limitless-miq")
        self.assertEqual(p["window_class"], "wind_down")
        self.assertEqual(p["stale_after_s"], jobs.MIQ_STALE_S)
        self.assertEqual(p["script"], "limitless-miq.sh")
        self.assertEqual(p["schedule"], cron_spec.POLL)
        self.assertEqual(cron_spec.job_spec(jobs.WAKE_BRIEF)["window_class"], "anytime")
        self.assertEqual(cron_spec.job_spec(jobs.OUTAGE_RECAP)["name"], "limitless-outage_recap")

    def test_jobs_that_send_nothing_get_no_payload(self):
        for spec in (jobs.NOOP_EXPORT, jobs.APPS_INGEST, jobs.RANKED_INGEST, jobs.SENDER_INGEST, jobs.FIT_INGEST):
            with self.subTest(job=spec.name):
                self.assertEqual(cron_spec.job_spec(spec), {})
                self.assertIn(spec.name, cron_spec.SENDS_NOTHING)

    def test_all_specs_is_every_module_spec_once(self):
        names = [s.name for s in cron_spec.all_specs()]
        self.assertEqual(len(names), len(set(names)))
        module = {v.name for v in vars(jobs).values() if isinstance(v, jobs.JobSpec)}
        self.assertEqual(set(names), module)
        self.assertLessEqual(cron_spec.SENDS_NOTHING, module)

    def test_the_poll_is_an_interval_not_a_clock_time(self):
        self.assertEqual(fork_parse_every(cron_spec.POLL)["kind"], "interval")
        self.assertNotRegex(cron_spec.POLL, r"(?i)\b(am|pm|at|monday|daily|weekdays)\b|:")

    def test_a_new_dict_each_call(self):
        a = cron_spec.job_spec(jobs.MIQ)
        a["window_class"] = "peak"
        self.assertEqual(cron_spec.job_spec(jobs.MIQ)["window_class"], "wind_down")

    def test_a_spec_with_no_window_is_refused(self):
        with self.assertRaises(ValueError):
            cron_spec.job_spec(SimpleNamespace(name="synthetic", window_class=None))


class PlanWords(unittest.TestCase):
    def test_stale_words(self):
        w = cron_spec.stale_words
        self.assertEqual(w(None), "never stale")
        self.assertEqual(w(3600), "stale after one hour")
        self.assertEqual(w(3 * 3600), "stale after three hours")
        self.assertEqual(w(12 * 3600), "stale after twelve hours")
        self.assertEqual(w(1800), "stale after under an hour")
        self.assertEqual(w(5400), "stale after about one hour")   # rounded down, said as about
        self.assertEqual(w(3 * 86400), "stale after over a day")

    def test_plan_lines_have_no_digits_and_name_every_job(self):
        lines = cron_spec.plan_lines()
        self.assertEqual(len(lines), len(cron_spec.all_specs()))
        for line, spec in zip(lines, cron_spec.all_specs()):
            with self.subTest(job=spec.name):
                self.assertFalse(re.search(r"\d", line), line)
        text = "\n".join(lines)
        self.assertIn("limitless-miq (MIQ for tonight?): window wind down, stale after three hours", text)
        self.assertIn("limitless-noop_export (NOOP export): skipped, sends nothing", text)


class Cli(unittest.TestCase):
    def run_cli(self, home, *args):
        keep = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")}
        return subprocess.run([sys.executable, "-I", str(BIN), *args], env=child_env(dict(keep, HOME=str(home))),
                              capture_output=True, text=True, timeout=60, cwd=str(home))

    def listing(self, root):
        return sorted((str(p.relative_to(root)), p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*"))

    def test_words_and_json_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".hermes" / "scripts").mkdir(parents=True)
            before = self.listing(home)
            words = self.run_cli(home)
            out = self.run_cli(home, "--json")
            after = self.listing(home)
        self.assertEqual(words.returncode, 0, words.stderr)
        self.assertFalse(re.search(r"\d", words.stdout), words.stdout)
        self.assertEqual(words.stdout.splitlines(), cron_spec.plan_lines())
        self.assertEqual(out.returncode, 0, out.stderr)
        payloads = json.loads(out.stdout)
        self.assertEqual(payloads, [p for p in (cron_spec.job_spec(s) for s in cron_spec.all_specs()) if p])
        self.assertEqual(before, after)

    def test_bad_argument_is_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self.run_cli(Path(tmp), "--send")
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage", r.stderr)
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
