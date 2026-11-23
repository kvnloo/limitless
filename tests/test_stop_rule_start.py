"""A stop rule is picked from a short fixed list when the habit week starts and stored in habit.json through
habit_start's atomic 0600 write. No free text, no number, no clock time. Synthetic data only; nothing sends."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_start, plugin, stop_rule  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state"
CLI = ROOT / "bin" / "limitless-habit-start"
NOW = 2_000_000_000.0
TODAY = date.fromtimestamp(NOW)
BANNED = re.compile(r"(?i)\d|streak|missed|failed|\bmust\b|\bshould\b|\b(am|pm)\b|o'clock")


class RuleList(unittest.TestCase):
    def test_a_short_fixed_list_of_word_rules(self):
        self.assertEqual(list(stop_rule.RULES), ["most_done", "any_done", "not_a_chore", "no_rule"])
        self.assertEqual(stop_rule.RULES["most_done"], "drop it unless most logged days were Done")
        self.assertEqual(stop_rule.RULES["no_rule"], "no rule: decide at the review")
        for rid, words in stop_rule.RULES.items():
            self.assertIsNone(BANNED.search(rid), rid)
            self.assertIsNone(BANNED.search(words), words)

    def test_rule_reads_only_a_listed_id(self):
        self.assertEqual(stop_rule.rule("most_done"), "most_done")
        self.assertEqual(stop_rule.rule(" Most_Done "), "most_done")
        for bad in (None, "", "drop it if I feel like it", "at_least 4 of 7", 3, ["most_done"]):
            self.assertIsNone(stop_rule.rule(bad), bad)

    def test_rule_of_reads_habit_json(self):
        self.assertEqual(stop_rule.rule_of({"stop_rule": "any_done"}), "any_done")
        self.assertIsNone(stop_rule.rule_of({"stop_rule": "free text"}))
        self.assertIsNone(stop_rule.rule_of({}))
        self.assertIsNone(stop_rule.rule_of(None))


class StartWithRule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name) / "state"
        self.st.mkdir()
        self.hj = self.st / "habit.json"

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, write=True, **kw):
        return habit_start.start_week(self.st, "Synthetic habit", TODAY, write, now=NOW, **kw)

    def test_the_rule_is_written_beside_the_week_0600(self):
        r = self.start(stop_rule="most_done")
        self.assertEqual((r["action"], r["stop_rule"]), (habit_start.STARTED, "most_done"))
        got = json.loads(self.hj.read_text())
        self.assertEqual((got["week_of"], got["stop_rule"]), (TODAY.isoformat(), "most_done"))
        self.assertEqual(stat.S_IMODE(self.hj.stat().st_mode), 0o600)

    def test_dry_run_names_the_rule_and_writes_nothing(self):
        r = self.start(write=False, stop_rule="no_rule")
        self.assertEqual((r["action"], r["stop_rule"]), (habit_start.WOULD_START, "no_rule"))
        self.assertEqual(list(self.st.iterdir()), [])

    def test_a_rule_off_the_list_is_refused_and_nothing_is_written(self):
        for bad in ("drop it if I feel like it", "at_least 4 of 7", "", 7):
            r = self.start(stop_rule=bad)
            self.assertEqual(r["action"], habit_start.REFUSED, bad)
            self.assertIsNone(BANNED.search(r["reason"]), r["reason"])
            self.assertEqual(list(self.st.iterdir()), [])

    def test_no_rule_given_keeps_habit_json_as_before(self):
        r = self.start()
        self.assertIsNone(r["stop_rule"])
        self.assertNotIn("stop_rule", json.loads(self.hj.read_text()))


class ToolAndCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name) / "st"
        shutil.copytree(FIX, self.st)
        (self.st / "habit.json").unlink()
        self.hj = self.st / "habit.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_schema_offers_the_rule_ids(self):
        props = plugin.TOOLS["limitless_habit"][0]["parameters"]["properties"]
        self.assertEqual(props["stop_rule"]["enum"], list(stop_rule.RULES))

    def test_tool_start_writes_the_rule_only_with_confirm(self):
        env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(Path(self.tmp.name) / "none.json")}
        call = plugin._handler(plugin.TOOLS["limitless_habit"][1])
        with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=NOW):
            dry = json.loads(call({"start": "Synthetic habit", "stop_rule": "any_done"}))
            self.assertEqual(dry["value"]["stop_rule"], "any_done")
            self.assertFalse(self.hj.exists())
            json.loads(call({"start": "Synthetic habit", "stop_rule": "any_done", "confirm": True}))
        self.assertEqual(json.loads(self.hj.read_text())["stop_rule"], "any_done")

    def test_cli_takes_a_listed_rule(self):
        env = {"HOME": self.tmp.name, "PATH": os.environ.get("PATH", ""), "LIMITLESS_STATE": str(self.st),
               "LIMITLESS_CONFIG": str(Path(self.tmp.name) / "none.json")}
        r = subprocess.run([sys.executable, "-I", str(CLI), "Synthetic habit", "--stop-rule", "not_a_chore", "--write"],
                           env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.hj.read_text())["stop_rule"], "not_a_chore")
        bad = subprocess.run([sys.executable, "-I", str(CLI), "Synthetic habit", "--stop-rule", "whenever"],
                             env=env, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(bad.returncode, 0)


if __name__ == "__main__":
    unittest.main()
