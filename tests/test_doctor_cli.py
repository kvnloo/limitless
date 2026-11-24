"""bin/limitless-doctor end to end: words only, never a raw value, exit 0 unless --strict. Synthetic state only."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-doctor"
sys.path.insert(0, str(ROOT))
from limitless import doctor  # noqa: E402
# obvious raw numbers planted in the synthetic state: none may reach the output
RAW = ["87654.3", "61.7", "27183", "31.4", "4.25", "93.1", "7.77", "18.9"]


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class LimitlessDoctorCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
        self.env["HOME"] = str(self.home)
        self.cfg = {"state": str(self.st)}
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def write(self, name, rows):
        text = "\n".join(json.dumps(r) for r in rows) if isinstance(rows, list) else json.dumps(rows)
        (self.st / name).write_text(text + "\n")

    def fresh(self, **ages):
        self.write("inputs.json", {"at": iso(self.now), "ageHours": ages})
        self.write("runs.jsonl", [{"at": iso(self.now - timedelta(hours=2)), "job": "sync", "ok": True,
                                   "took_s": 7.77}])

    def run_cli(self, *args, **env):
        cfg = self.home / ".config/limitless/config.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps(self.cfg))
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(dict(self.env, **env)), cwd=self.home,
                              capture_output=True, text=True, timeout=60)

    def test_text_is_one_line_per_row_with_words_only(self):
        self.fresh(wearable=1.5, scale=40.0)
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertIn("state dir: live: the state dir exists and is readable", lines)
        self.assertIn("input wearable: live: recording: updated within the last day", lines)
        self.assertIn("input scale: stale: not recording: no update for over a day", lines)
        self.assertIn("last sync run: live: the last sync run was about two hours ago and finished ok", lines)
        self.assertIn('tool limitless_body: off: no body file: set "body_file" in config.json', lines)
        for ln in lines:
            name, status, reason = ln.split(": ", 2)
            self.assertIn(status, ("live", "stale", "missing", "off"), ln)
            for key in doctor.CONFIG_KEYS_WITH_A_DIGIT:   # a config key's name, not a value
                reason = reason.replace(key, "")
            self.assertFalse(any(c.isdigit() for c in status + reason), ln)

    def test_json_is_the_full_rows(self):
        self.fresh(wearable=1.5)
        r = self.run_cli("--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)
        self.assertEqual(rows[0], {"name": "state dir", "kind": "state", "status": "live",
                                   "reason": "the state dir exists and is readable"})
        self.assertTrue(all(set(x) == {"name", "kind", "status", "reason"} for x in rows))
        self.assertEqual(len(r.stdout.splitlines()), len(rows) + 2)   # one row per line inside [ ]

    def test_exit_zero_even_when_nothing_is_live(self):
        self.cfg = {"state": str(self.home / "nowhere")}
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("state dir: missing: the state dir does not exist", r.stdout.splitlines())

    def test_strict_exits_one_when_an_input_row_is_not_live(self):
        self.fresh(wearable=1.5, bike="down")
        r = self.run_cli("--strict")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("input bike: stale: not recording: the sync reports it down", r.stdout.splitlines())

    def test_strict_exits_zero_when_every_input_row_is_live_even_with_tools_off(self):
        self.fresh(wearable=1.5, phone=0.5)
        r = self.run_cli("--strict")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("tool limitless_anki: off: no Anki collection set", r.stdout.splitlines())

    def test_no_raw_value_is_ever_printed(self):
        night = (self.now - timedelta(days=1)).date().isoformat()
        day = self.now.date().isoformat()
        self.fresh(wearable=4.25, scale=18.9)
        self.write("digests.jsonl", [{"date": day, "at": iso(self.now),
                                      "metrics": {"sleep_h": {"value": 7.77, "modality": "measured"},
                                                  "readiness": {"value": 93.1, "modality": "measured"},
                                                  "steps": {"value": 87654.3, "modality": "measured"}}}])
        self.write("sleep.jsonl", [{"night": night, "asleep_s": 27183, "source": "wearable"}])
        self.write("presleep.jsonl", [{"night": night, "bpm": 61.7, "modality": "measured"}])
        self.write("body.jsonl", [{"day": day, "bf_pct": 31.4, "method": "scale", "calibrated": False}])
        self.cfg.update(sleep_file="sleep.jsonl", presleep_hr_file="presleep.jsonl", body_file="body.jsonl")
        for raw_opt_in in ("0", "1"):   # even the person's raw opt-in never makes the doctor print a value
            for args in ((), ("--json",)):
                r = self.run_cli(*args, LIMITLESS_RAW_IN_PROMPT=raw_opt_in)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("tool limitless_sleep", r.stdout)
                for n in RAW:
                    self.assertNotIn(n, r.stdout, (args, raw_opt_in))
                    self.assertNotIn(n.split(".")[0], r.stdout, (args, raw_opt_in))
                self.assertEqual(r.stderr, "")

    def test_it_writes_nothing_to_the_state_dir(self):
        self.fresh(wearable=1.5)
        before = sorted((str(p), p.stat().st_mtime_ns, p.read_bytes()) for p in self.st.rglob("*"))
        self.run_cli()
        self.run_cli("--json", "--strict")
        self.assertEqual(sorted((str(p), p.stat().st_mtime_ns, p.read_bytes()) for p in self.st.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
