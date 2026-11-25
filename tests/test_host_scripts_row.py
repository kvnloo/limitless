"""The doctor's `host job scripts` row: are the limitless-<job>.sh files bin/limitless-cron-spec --scripts writes in
the dir config host_scripts_dir names, and are they this plugin's current text and mode?

Synthetic temp dirs only. The row reads each script as text: it never runs, writes, chmods or deletes anything.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermetic_env import child_env

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import cron_spec, doctor, jobs  # noqa: E402

ROW = "host job scripts"
OFF = "no host scripts dir set (config host_scripts_dir)"
NO_DIR = "the host scripts dir does not exist"
OK = "every sending job has its current script"
NOT_THERE = "some scripts are not there: "
DIFFER = "some scripts differ from this plugin's: "


def name(spec):
    return f"limitless-{spec.name}.sh"


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.dir = self.root / "scripts"
        p = mock.patch.dict(os.environ, {}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def fill(self, skip=(), mode=0o700):
        """Every current script into self.dir, as bin/limitless-cron-spec --scripts writes them, but ``skip``."""
        self.dir.mkdir(exist_ok=True)
        for n, body in cron_spec.scripts().items():
            if n in skip:
                continue
            if (self.dir / n).exists():
                os.chmod(self.dir / n, 0o600)   # an earlier subtest may have left it read-only
            (self.dir / n).write_text(body, encoding="utf-8")
            os.chmod(self.dir / n, mode)

    def row(self, cfg=None):
        return doctor.host_scripts_row({"host_scripts_dir": str(self.dir)} if cfg is None else cfg)

    def check(self, r, status, reason):
        self.assertEqual((r["name"], r["kind"], r["status"], r["reason"]), (ROW, "source", status, reason))
        self.assertEqual(doctor.text([r]), f"{ROW}: {status}: {reason}")
        self.assertNotRegex(r["reason"], r"\d")
        self.assertNotIn(str(self.root), r["reason"])
        self.assertNotIn("/", r["reason"])


class Off(Case):
    def test_key_not_set_is_off(self):
        self.check(self.row({}), doctor.OFF, OFF)

    def test_blank_or_not_a_string_is_off(self):
        for v in ("", "   ", None, 7, ["x"]):
            self.check(self.row({"host_scripts_dir": v}), doctor.OFF, OFF)

    def test_not_a_mapping_is_off(self):
        self.check(doctor.host_scripts_row("not a dict"), doctor.OFF, OFF)


class Missing(Case):
    def test_the_dir_does_not_exist(self):
        self.check(self.row(), doctor.MISSING, NO_DIR)

    def test_a_file_where_the_dir_should_be_is_no_dir(self):
        self.dir.write_text("not a dir")
        self.check(self.row(), doctor.MISSING, NO_DIR)

    def test_an_empty_dir_names_every_sending_job(self):
        self.dir.mkdir()
        r = self.row()
        self.check(r, doctor.MISSING, NOT_THERE + "wake brief, back from nap, MIQ, habit check-in, week review, "
                                                  "break nudge, outage recap and sender confirmation")

    def test_two_missing_scripts_are_named_in_words(self):
        self.fill(skip={name(jobs.SPECS["nap"]), name(jobs.SPECS["week_review"])})
        self.check(self.row(), doctor.MISSING, NOT_THERE + "back from nap and week review")

    def test_one_missing_script(self):
        self.fill(skip={name(jobs.SPECS["nap"])})
        self.check(self.row(), doctor.MISSING, NOT_THERE + "back from nap")

    def test_a_job_that_sends_nothing_needs_no_script(self):
        self.fill()
        self.assertFalse((self.dir / "limitless-noop_export.sh").exists())
        self.check(self.row(), doctor.LIVE, OK)

    def test_missing_and_stale_together_say_both_and_stay_missing(self):
        self.fill(skip={name(jobs.SPECS["nap"])})
        os.chmod(self.dir / name(jobs.SPECS["miq"]), 0o644)
        self.check(self.row(), doctor.MISSING, NOT_THERE + "back from nap; " + DIFFER + "MIQ")

    def test_a_tilde_path_is_expanded(self):
        home = Path(os.path.expanduser("~"))
        self.check(self.row({"host_scripts_dir": "~/no-such-scripts-dir"}), doctor.MISSING, NO_DIR)
        self.assertFalse((home / "no-such-scripts-dir").exists())


class Stale(Case):
    def test_an_old_body_is_stale(self):
        self.fill()
        p = self.dir / name(jobs.SPECS["nap"])
        old = p.read_text().replace(f" {cron_spec.JOB_FLAGS}\n", "\n")   # an older plugin's script: no --send
        self.assertNotEqual(old, p.read_text())
        p.write_text(old)
        self.check(self.row(), doctor.STALE, DIFFER + "back from nap")

    def test_a_body_from_another_script_body_is_stale(self):
        self.fill()
        with mock.patch.object(cron_spec, "JOB_FLAGS", "--send --old-flag"):
            old = cron_spec.script_body(jobs.SPECS["week_review"])
        (self.dir / name(jobs.SPECS["week_review"])).write_text(old)
        self.check(self.row(), doctor.STALE, DIFFER + "week review")

    def test_mode_0644_is_stale(self):
        self.fill()
        os.chmod(self.dir / name(jobs.SPECS["nap"]), 0o644)
        self.check(self.row(), doctor.STALE, DIFFER + "back from nap")

    def test_group_or_world_bits_are_stale(self):
        for mode in (0o755, 0o750, 0o701, 0o600, 0o400, 0o300):
            with self.subTest(mode=oct(mode)):
                self.fill()
                os.chmod(self.dir / name(jobs.SPECS["nap"]), mode)
                self.check(self.row(), doctor.STALE, DIFFER + "back from nap")

    def test_owner_read_and_execute_only_is_fine(self):
        self.fill(mode=0o500)
        self.check(self.row(), doctor.LIVE, OK)

    def test_crlf_line_ends_are_stale(self):
        self.fill()
        p = self.dir / name(jobs.SPECS["nap"])
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
        self.check(self.row(), doctor.STALE, DIFFER + "back from nap")

    def test_not_text_is_stale(self):
        self.fill()
        (self.dir / name(jobs.SPECS["nap"])).write_bytes(b"\xff\xfe\x00 not a script")
        self.check(self.row(), doctor.STALE, DIFFER + "back from nap")

    def test_a_dir_with_the_script_name_is_stale(self):
        self.fill(skip={name(jobs.SPECS["nap"])})
        (self.dir / name(jobs.SPECS["nap"])).mkdir(mode=0o700)
        self.check(self.row(), doctor.STALE, DIFFER + "back from nap")

    def test_three_stale_scripts_in_spec_order(self):
        self.fill()
        for j in ("break_nudge", "nap", "wake_brief"):
            os.chmod(self.dir / name(jobs.SPECS[j]), 0o644)
        self.check(self.row(), doctor.STALE, DIFFER + "wake brief, back from nap and break nudge")


class Ok(Case):
    def test_every_current_script_is_live(self):
        self.fill()
        self.check(self.row(), doctor.LIVE, OK)

    def test_extra_files_are_ignored(self):
        self.fill()
        (self.dir / "limitless-retired_job.sh").write_text("#!/bin/sh\nexit 0\n")
        (self.dir / "notes.txt").write_text("other host scripts live here too")
        os.chmod(self.dir / "notes.txt", 0o644)
        self.check(self.row(), doctor.LIVE, OK)

    def test_the_files_bin_limitless_cron_spec_writes_are_live(self):
        self.dir.mkdir()
        r = subprocess.run([sys.executable, "-I", str(Path(doctor.__file__).resolve().parents[1] / "bin" /
                                                     "limitless-cron-spec"), "--scripts", str(self.dir)],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.check(self.row(), doctor.LIVE, OK)


class ReadOnly(Case):
    def snapshot(self):
        out = {}
        for p in sorted(self.dir.iterdir()):
            st = p.stat()
            out[p.name] = (st.st_mtime_ns, stat.S_IMODE(st.st_mode), p.read_bytes())
        return out

    def test_it_never_runs_writes_chmods_or_deletes(self):
        self.fill(skip={name(jobs.SPECS["nap"])})
        os.chmod(self.dir / name(jobs.SPECS["miq"]), 0o644)
        (self.dir / "extra.sh").write_text("#!/bin/sh\n")
        before = self.snapshot()

        def boom(*a, **k):
            raise AssertionError("the row must not do this")

        with mock.patch.object(subprocess, "run", boom), mock.patch.object(subprocess, "Popen", boom), \
                mock.patch.object(os, "chmod", boom), mock.patch.object(os, "unlink", boom), \
                mock.patch.object(os, "remove", boom), mock.patch.object(os, "replace", boom), \
                mock.patch.object(os, "rename", boom), mock.patch.object(os, "system", boom), \
                mock.patch.object(os, "execv", boom), mock.patch.object(os, "mkdir", boom):
            self.row()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.dir / name(jobs.SPECS["nap"])).exists())

    def test_files_are_opened_for_reading_only(self):
        self.fill()
        real = open
        modes = []

        def spy(file, mode="r", *a, **k):
            modes.append(mode)
            return real(file, mode, *a, **k)

        with mock.patch("builtins.open", spy):
            self.check(self.row(), doctor.LIVE, OK)
        self.assertTrue(modes)
        self.assertTrue(all(set(m) <= set("rbt") for m in modes), modes)


class InTheReport(Case):
    def test_it_comes_right_after_the_cron_window_provider_row(self):
        st = self.root / "state"
        st.mkdir()
        rows = doctor.report({"state": str(st)}, 1894708800.0)
        names = [r["name"] for r in rows]
        at = names.index(doctor.CRON_WINDOW_ROW)
        self.assertEqual(names[at + 1], ROW)
        self.assertEqual(names[at + 2], doctor.HOST_JOBS_ROW)   # then the host job records row
        self.assertEqual(names[at + 3], doctor.DESKTOP_AW_ROW)
        self.assertEqual(rows[at + 1]["status"], doctor.OFF)

    def test_the_report_reads_the_config_key(self):
        st = self.root / "state"
        st.mkdir()
        self.fill()
        rows = doctor.report({"state": str(st), "host_scripts_dir": str(self.dir)}, 1894708800.0)
        r = next(r for r in rows if r["name"] == ROW)
        self.assertEqual((r["status"], r["reason"]), (doctor.LIVE, OK))


if __name__ == "__main__":
    unittest.main()
