"""cron_spec.plan_commands and bin/limitless-cron-spec --plan <jobs file> --cli: the update plan as the host's own
``hermes cron`` commands, for an operator to review and paste. Nothing here runs them.

The flags are the ones the public fork kvnloo/hermes-agent, branch up/cron-decision-window-gate-r2 (read at
a910662), parses in hermes_cli/subcommands/cron.py: ``create`` takes the schedule as its first positional (line
54), an optional prompt (lines 55-56), ``--name`` (57), ``--deliver`` (58-62), ``--script`` (73-78) and
``--no-agent`` (79-82); ``edit`` takes the job id or name (136), ``--schedule`` (137), ``--name`` (139),
``--deliver`` (140), ``--script`` (154-157, '' clears) and ``--no-agent`` / ``--agent`` (158-163). Neither parser
has a flag for ``window_class`` or ``stale_after_s``, hermes_cli/cron.py's _JOB_ARG_FIELDS (lines 781-788) passes
none on, and the cronjob tool's signature (tools/cronjob_tools.py lines 1059-1093) has no such field either.
The parser also has pause (204-205), resume (207-210) and remove/rm/delete (222-224); a plan never uses them.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import copy
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hermetic_env import child_env  # noqa: E402
from limitless import cron_spec  # noqa: E402
from test_cron_records_diff import in_sync  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "limitless-cron-spec"
FIXTURE = ROOT / "tests" / "fixtures" / "cron" / "jobs-plan.json"
# The flags each fork subcommand parses (hermes_cli/subcommands/cron.py lines 52-133 and 135-201) that a plan may
# use; the value-taking ones are listed with their "=" spelling too.
CREATE_FLAGS = {"--name", "--deliver", "--script", "--no-agent"}
EDIT_FLAGS = {"--schedule", "--name", "--deliver", "--script", "--no-agent", "--agent"}
NEVER = ("delete", "remove", "rm", "pause", "resume")
NO_FLAG = "has no hermes cron flag"


def fixture_records():
    return cron_spec.records_in(json.loads(FIXTURE.read_text(encoding="utf-8")))


def payload(name):
    return next(p for p in cron_spec.payloads() if p["name"] == name)


def flags_of(tokens):
    return {t.split("=", 1)[0] for t in tokens if t.startswith("--")}


class PlanCommands(unittest.TestCase):
    def test_a_missing_job_is_a_create_line_and_a_comment_for_window_and_expiry(self):
        nap = payload("limitless-nap")
        lines = cron_spec.plan_commands([{"job": "limitless-nap", "call": "create_job", "kwargs": nap}])
        self.assertEqual(lines, [
            "hermes cron create 'every 5m' --name limitless-nap --script limitless-nap.sh --no-agent --deliver local",
            "# limitless-nap: window and expiry " + NO_FLAG + cron_spec.NO_FLAG_TAIL,
        ])

    def test_differs_is_an_edit_line_with_only_the_differing_flags(self):
        step = {"job": "limitless-miq", "call": "update_job", "job_id": "a00000000002",
                "updates": {"schedule": {"kind": "interval", "minutes": 5, "display": "every 5m"},
                            "deliver": "local"}}
        self.assertEqual(cron_spec.plan_commands([step]),
                         ["hermes cron edit a00000000002 --schedule 'every 5m' --deliver local"])

    def test_every_flagged_field_on_edit(self):
        step = {"job": "limitless-nap", "call": "update_job", "job_id": "a00000000001",
                "updates": {"schedule": {"kind": "interval", "minutes": 5, "display": "every 5m"},
                            "script": "limitless-nap.sh", "no_agent": True, "deliver": "local"}}
        self.assertEqual(cron_spec.plan_commands([step]), [
            "hermes cron edit a00000000001 --schedule 'every 5m' --script limitless-nap.sh --no-agent --deliver local"])
        step["updates"] = {"no_agent": False, "script": None}
        self.assertEqual(cron_spec.plan_commands([step]), ["hermes cron edit a00000000001 --script '' --agent"])

    def test_a_field_without_a_flag_is_a_comment_never_dropped(self):
        step = {"job": "limitless-nap", "call": "update_job", "job_id": "a00000000001",
                "updates": {"window_class": "anytime"}}
        self.assertEqual(cron_spec.plan_commands([step]),
                         ["# limitless-nap: window " + NO_FLAG + cron_spec.NO_FLAG_TAIL])
        step["updates"] = {"stale_after_s": 10800.0, "script": "limitless-nap.sh"}
        self.assertEqual(cron_spec.plan_commands([step]), [
            "hermes cron edit a00000000001 --script limitless-nap.sh",
            "# limitless-nap: expiry " + NO_FLAG + cron_spec.NO_FLAG_TAIL])
        step["updates"] = {"stale_after_s": None, "deliver": None}   # clearing either has no flag either
        self.assertEqual(cron_spec.plan_commands([step]),
                         ["# limitless-nap: delivery and expiry " + NO_FLAG + cron_spec.NO_FLAG_TAIL])

    def test_none_is_a_comment_with_its_reason(self):
        steps = [{"job": "limitless-sender_confirm", "call": "none",
                  "why": "more than one host job with this name; keep one by hand, then plan again"}]
        self.assertEqual(cron_spec.plan_commands(steps), [
            "# limitless-sender_confirm: more than one host job with this name; keep one by hand, then plan again"])

    def test_values_are_shell_quoted(self):
        step = {"job": "limitless-nap", "call": "update_job", "job_id": "a job's id",
                "updates": {"script": "my script's \"name\".sh", "deliver": "platform:chat id"}}
        (line,) = cron_spec.plan_commands([step])
        self.assertEqual(shlex.split(line), ["hermes", "cron", "edit", "a job's id", "--script",
                                             "my script's \"name\".sh", "--deliver", "platform:chat id"])
        self.assertTrue(line.startswith("hermes cron edit 'a job'\"'\"'s id' "), line)

    def test_a_value_starting_with_a_dash_is_never_read_as_a_flag(self):
        step = {"job": "limitless-nap", "call": "update_job", "job_id": "a00000000001",
                "updates": {"script": "--help.sh"}}
        (line,) = cron_spec.plan_commands([step])
        self.assertEqual(shlex.split(line)[3:], ["a00000000001", "--script=--help.sh"])
        step["job_id"] = "-x"   # a positional cannot take the "=" spelling: the line is a comment instead
        (line,) = cron_spec.plan_commands([step])
        self.assertTrue(line.startswith("# limitless-nap: "), line)

    def test_a_record_name_or_id_cannot_break_out_of_its_line(self):
        evil = "limitless-old\nhermes cron remove a00000000001"
        steps = [{"job": evil, "call": "none", "why": cron_spec.RETIRED},
                 {"job": "limitless-nap", "call": "update_job", "job_id": "a1\nhermes cron pause a2",
                  "updates": {"deliver": "local"}}]
        lines = cron_spec.plan_commands(steps)
        self.assertEqual(len(lines), 2)
        for line in lines:
            with self.subTest(line=line):
                self.assertNotIn("\n", line)
                self.assertNotIn("\r", line)
                self.assertTrue(line.startswith("# "), line)

    def test_no_line_is_ever_a_delete_pause_or_resume(self):
        plans = [cron_spec.update_plan(fixture_records(), cron_spec.payloads()),
                 cron_spec.update_plan([], cron_spec.payloads())]
        for plan in plans:
            for line in cron_spec.plan_commands(plan):
                with self.subTest(line=line):
                    if line.startswith("# "):
                        for word in ("pause", "resume", "delete"):
                            self.assertNotIn(word, line)
                        continue
                    tokens = shlex.split(line)
                    self.assertIn(tokens[:3], (["hermes", "cron", "create"], ["hermes", "cron", "edit"]))
                    self.assertFalse(set(tokens) & set(NEVER), line)
                    self.assertLessEqual(flags_of(tokens), CREATE_FLAGS if tokens[2] == "create" else EDIT_FLAGS)

    def test_the_fixture_plan_one_or_two_lines_per_step(self):
        plan = cron_spec.update_plan(fixture_records(), cron_spec.payloads())
        lines = cron_spec.plan_commands(plan)
        n = 0
        for step in plan:
            mine = cron_spec.plan_commands([step])
            with self.subTest(job=step["job"]):
                self.assertEqual(lines[n:n + len(mine)], mine)
                self.assertIn(len(mine), (1, 2))
                if step["call"] == "none":
                    self.assertEqual(mine, [f"# {step['job']}: {step['why']}"])
                if step["call"] == "update_job" and set(step["updates"]) & {"window_class", "stale_after_s"}:
                    self.assertTrue(mine[-1].startswith(f"# {step['job']}: ") and NO_FLAG in mine[-1], mine)
            n += len(mine)
        self.assertEqual(n, len(lines))
        # the fixture's nap record differs in its window only: no edit line at all, the comment says why
        self.assertEqual(cron_spec.plan_commands([s for s in plan if s["job"] == "limitless-nap"]),
                         ["# limitless-nap: window " + NO_FLAG + cron_spec.NO_FLAG_TAIL])

    def test_every_create_in_a_full_plan(self):
        plan = cron_spec.update_plan([], cron_spec.payloads())
        lines = cron_spec.plan_commands(plan)
        creates = [shlex.split(line) for line in lines if not line.startswith("#")]
        self.assertEqual([t[t.index("--name") + 1] for t in creates], [p["name"] for p in cron_spec.payloads()])
        self.assertEqual(sum(1 for line in lines if NO_FLAG in line), len(cron_spec.payloads()))

    def test_in_step_is_no_lines_and_pure(self):
        self.assertEqual(cron_spec.plan_commands(cron_spec.update_plan(in_sync(), cron_spec.payloads())), [])
        plan = cron_spec.update_plan(fixture_records(), cron_spec.payloads())
        before = copy.deepcopy(plan)
        self.assertEqual(cron_spec.plan_commands(plan), cron_spec.plan_commands(plan))
        self.assertEqual(plan, before)


class PlanCliFlag(unittest.TestCase):
    def run_cli(self, home, *args):
        keep = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")}
        return subprocess.run([sys.executable, "-I", str(BIN), *args], env=child_env(dict(keep, HOME=str(home))),
                              capture_output=True, text=True, timeout=60, cwd=str(home))

    def listing(self, root):
        return sorted((str(p.relative_to(root)), p.stat().st_mtime_ns, p.stat().st_size, p.stat().st_mode)
                      for p in root.rglob("*"))

    def test_drift_prints_the_commands_and_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self.run_cli(Path(tmp), "--plan", str(FIXTURE), "--cli")
        self.assertEqual(r.returncode, 1, r.stderr)
        want = cron_spec.plan_commands(cron_spec.update_plan(fixture_records(), cron_spec.payloads()))
        self.assertEqual(r.stdout, "".join(line + "\n" for line in want))
        self.assertIn("hermes cron create ", r.stdout)
        self.assertIn("hermes cron edit ", r.stdout)

    def test_in_step_prints_nothing_exits_zero_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            jobs = home / ".hermes" / "cron" / "jobs.json"
            jobs.parent.mkdir(parents=True)
            jobs.write_text(json.dumps({"jobs": in_sync()}), encoding="utf-8")
            jobs.chmod(0o400)
            before = self.listing(home)
            r = self.run_cli(home, "--plan", str(jobs), "--cli")
            after = self.listing(home)
            jobs.chmod(0o600)
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        self.assertEqual(before, after)

    def test_usage_and_unreadable_files_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "bad.json").write_text("{not json", encoding="utf-8")
            cases = (("--cli",), ("--plan", "--cli"), ("--plan", str(FIXTURE), "--cli", "x"),
                     ("--plan", str(FIXTURE), "--json"), ("--check", str(FIXTURE), "--cli"),
                     ("--plan", str(home / "absent.json"), "--cli"), ("--plan", str(home / "bad.json"), "--cli"))
            results = [(args, self.run_cli(home, *args)) for args in cases]
        for args, r in results:
            with self.subTest(args=args):
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(r.stdout, "")
                self.assertTrue(r.stderr.strip())
                self.assertNotIn("Traceback", r.stderr)

    def test_the_doc_and_usage_name_the_flag_and_the_gap(self):
        doc = (ROOT / "docs" / "decision-window.md").read_text(encoding="utf-8")
        self.assertIn("limitless-cron-spec --plan <the host's cron/jobs.json> --cli", doc)
        para = next(p for p in doc.split("\n\n") if "--cli" in p)
        for words in ("window_class", "stale_after_s", "hermes cron create", "hermes cron edit"):
            self.assertIn(words, para)
        self.assertGreater(doc.index(para), doc.index("limitless-cron-spec --plan <the host's cron/jobs.json>` reads"))
        self.assertIn("--cli", BIN.read_text(encoding="utf-8").split('"""')[1])


if __name__ == "__main__":
    unittest.main()
