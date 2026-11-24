"""bin/limitless-ow-export [--write]: off by default (config open_wearables_export); a dry run unless --write and
the config says write; --write merges the rows into config sleep_file with noop_export's merge and atomic write.
One night held by another source (the NOOP export's row) keeps that row: Open Wearables only fills the gaps.

Synthetic JSON only; the http callable is injected, so nothing touches the network. UTC stands in for the local zone.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import open_wearables as ow  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "open_wearables"
CLI = ROOT / "bin" / "limitless-ow-export"
UTC = timezone.utc
KEY = "ow-SYNTHETIC-key-7f3a9c"
USER = "00000000-0000-4000-8000-0000000000aa"
TODAY = date(2030, 1, 8)
NOW = 1893456000.0


class Fake:
    def __init__(self, *names):
        self.names, self.calls = list(names), []

    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        return 200, (FIX / self.names.pop(0)).read_bytes()


def pages():
    return Fake("sleep_page1.json", "sleep_page2.json")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.state = self.home / "state"
        self.state.mkdir()
        self.sleep = self.state / "sleep.jsonl"
        self.cfg = {"state": str(self.state), "sleep_file": "sleep.jsonl", "open_wearables_export": "write",
                    "open_wearables_url": "http://ow.example.invalid:8000", "open_wearables_user": USER}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, argv, http=None, key=KEY, cfg=None):
        p = self.home / "config.json"
        p.write_text(json.dumps(self.cfg if cfg is None else cfg))
        env = {"LIMITLESS_CONFIG": str(p)}
        if key is not None:
            env["LIMITLESS_OW_KEY"] = key
        out, err = io.StringIO(), io.StringIO()
        self.http = pages() if http is None else http
        code = ow.main(argv, env=env, home=self.home, tz=UTC, out=out, err=err, http=self.http, today=TODAY,
                       now=NOW)
        return code, out.getvalue(), err.getvalue()


class Modes(Base):
    def test_off_by_default_reads_nothing_and_writes_nothing(self):
        cfg = {k: v for k, v in self.cfg.items() if k != "open_wearables_export"}
        code, out, _ = self.run_cli(["--write"], cfg=cfg)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "the Open Wearables export is off (config open_wearables_export)")
        self.assertEqual(self.http.calls, [])
        self.assertFalse(self.sleep.exists())
        self.assertFalse((self.state / ow.MARK).exists())

    def test_an_unknown_mode_is_off(self):
        code, out, _ = self.run_cli([], cfg=dict(self.cfg, open_wearables_export="yes"))
        self.assertEqual((code, self.http.calls), (0, []))

    def test_a_dry_run_by_default_prints_counts_in_words_and_writes_nothing(self):
        code, out, err = self.run_cli([])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.strip(), "dry run: three nights of wearable sleep from Open Wearables; skipped one nap, "
                                      "one session not from a wearable, one session with no asleep time; nothing "
                                      "written (run with --write to write them)")
        self.assertFalse(self.sleep.exists())
        self.assertFalse(any(ch.isdigit() for ch in out))

    def test_write_is_a_dry_run_while_the_config_says_dry_run(self):
        code, out, _ = self.run_cli(["--write"], cfg=dict(self.cfg, open_wearables_export="dry_run"))
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("dry run: three nights"))
        self.assertIn('(config open_wearables_export "write" writes them)', out)
        self.assertFalse(self.sleep.exists())

    def test_bad_arguments(self):
        code, _, err = self.run_cli(["--force"])
        self.assertEqual(code, 2)
        self.assertEqual(err.strip(), ow.USAGE)


class Write(Base):
    def test_write_merges_the_rows_atomically_with_mode_0600(self):
        code, out, err = self.run_cli(["--write"])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("sleep file: written, three nights new or changed", out)
        self.assertEqual(stat.S_IMODE(self.sleep.stat().st_mode), 0o600)
        rows = StateReader(self.state).sleep_rows(today=TODAY, env={"LIMITLESS_CONFIG": str(self.home / "config.json")},
                                                  home=self.home)
        self.assertEqual([(r["night"], r["asleep_s"], r["source"]) for r in rows],
                         [("2030-01-01", 25200, "open_wearables"), ("2030-01-02", 23400, "open_wearables"),
                          ("2030-01-06", 26400, "open_wearables")])
        self.assertEqual([os.path.basename(p) for p in os.listdir(self.state) if p.endswith(".tmp")], [])

    def test_a_rerun_is_unchanged_and_byte_identical(self):
        self.run_cli(["--write"])
        before, mtime = self.sleep.read_bytes(), self.sleep.stat().st_mtime_ns
        code, out, _ = self.run_cli(["--write"])
        self.assertEqual(code, 0)
        self.assertIn("sleep file: unchanged", out)
        self.assertEqual((self.sleep.read_bytes(), self.sleep.stat().st_mtime_ns), (before, mtime))

    def test_a_night_another_source_holds_keeps_that_row(self):
        noop = {"night": "2030-01-01", "asleep_s": 24000, "source": "noop", "start": "2030-01-01T23:10:00Z",
                "end": "2030-01-02T06:50:00Z"}
        other = "not a row\n"
        self.sleep.write_text(other + json.dumps(noop) + "\n")
        code, out, _ = self.run_cli(["--write"])
        self.assertEqual(code, 0)
        self.assertIn("sleep file: written, two nights new or changed; one night kept from another source", out)
        lines = self.sleep.read_text().splitlines()
        self.assertEqual(lines[0], "not a row")
        rows = [json.loads(x) for x in lines[1:]]
        by_night = {}
        for r in rows:
            by_night.setdefault(r["night"], []).append(r["source"])
        self.assertEqual(by_night, {"2030-01-01": ["noop"], "2030-01-02": ["open_wearables"],
                                    "2030-01-06": ["open_wearables"]})
        self.assertIn(noop, rows)

    def test_a_row_of_ours_on_a_night_another_source_later_wrote_is_dropped(self):
        self.run_cli(["--write"])
        noop = {"night": "2030-01-02", "asleep_s": 22000, "source": "noop"}
        self.sleep.write_text(self.sleep.read_text() + json.dumps(noop) + "\n")
        self.run_cli(["--write"])
        rows = [json.loads(x) for x in self.sleep.read_text().splitlines()]
        self.assertEqual([r["source"] for r in rows if r["night"] == "2030-01-02"], ["noop"])

    def test_no_sleep_file_configured_is_an_error_and_nothing_is_written(self):
        cfg = {k: v for k, v in self.cfg.items() if k != "sleep_file"}
        code, out, err = self.run_cli(["--write"], cfg=cfg)
        self.assertEqual(code, 1)
        self.assertIn('sleep file: not configured (set "sleep_file" in config.json), not written', err)
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), [ow.MARK])

    def test_the_mark_records_the_run_in_words(self):
        self.run_cli(["--write"])
        mark = json.loads((self.state / ow.MARK).read_text())
        self.assertEqual(mark["outcome"], ow.DONE)
        self.assertEqual(mark["mode"], "write")
        self.assertEqual(mark["ran_at"], NOW)
        self.assertEqual(stat.S_IMODE((self.state / ow.MARK).stat().st_mode), 0o600)
        self.assertEqual(ow.load_mark(self.state)["outcome"], ow.DONE)

    def test_the_bin_script_runs_and_is_off_without_config(self):
        env = {"PATH": os.environ.get("PATH", ""), "LIMITLESS_CONFIG": str(self.home / "none.json"),
               "LIMITLESS_STATE": str(self.state), "HOME": str(self.home)}
        p = subprocess.run([sys.executable, "-I", str(CLI)], capture_output=True, text=True, env=child_env(env), timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), "the Open Wearables export is off (config open_wearables_export)")


if __name__ == "__main__":
    unittest.main()
