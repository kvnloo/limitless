"""The doctor's "Sleep mode" row: what the last sleepmode.jsonl row means for kevin-push's Sleep hold, in words.

kevin-push holds every non-critical push while the last row says on (and the poll is fresh). The poller closes a
phone Sleep rule left on far longer than a night once the owner is seen up, with an inferred off row that names the
rule in ``left_on``; the row says so. Synthetic sleepmode.jsonl files (old rows without rule/left_on too), a fixed
clock. Nothing is written or sent.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import doctor, sleepmode  # noqa: E402

NOW = 1894708800.0  # 2030-01-15T12:00:00Z, the fixture clock
H = 3600.0
DIGIT = re.compile(r"\d")
LEFT_ON = "left on, ignored since the owner was seen up"
STALE_ON = "stale: on far longer than a night; pushes are being held"


def iso(t):
    """The poller's ISO-8601 Z form of epoch ``t`` (kevin-push's asleep() reads the poll's ``at`` that way)."""
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name) / "state"
        self.st.mkdir()
        self.cfg = {"state": str(self.st)}
        p = mock.patch.dict(os.environ, {"HOME": self.tmp.name, "TZ": "UTC"}, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.poll(NOW - 60)

    def rows(self, *rows):
        (self.st / "sleepmode.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def poll(self, at, ok=True):
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": iso(at), "ok": ok}))

    def row(self, env=None):
        r = doctor.sleep_mode_row(self.cfg, NOW, env=env)
        self.assertEqual((r["name"], r["kind"]), ("Sleep mode", "source"))
        self.assertIsNone(DIGIT.search(r["reason"]), r)
        return r["status"], r["reason"]


class OnAndOff(Case):
    def test_an_old_on_row_without_a_rule_is_on_since_words(self):
        self.rows({"at": NOW - 10 * H, "on": False}, {"at": NOW - 4 * H, "on": True})
        self.assertEqual(self.row(), (doctor.LIVE, "on since about four hours ago"))

    def test_an_on_row_with_a_rule_and_an_iso_time(self):
        self.rows({"at": "2030-01-15T07:30:00Z", "on": True, "rule": "rule-a"})
        self.assertEqual(self.row(), (doctor.LIVE, "on since about four hours ago"))

    def test_on_since_counts_from_the_first_on_row_of_the_activation(self):
        self.rows({"at": NOW - 20 * H, "on": False}, {"at": NOW - 6 * H, "on": True, "rule": "rule-a"},
                  {"at": NOW - 1 * H, "on": True, "rule": "rule-a"})
        self.assertEqual(self.row(), (doctor.LIVE, "on since about six hours ago"))

    def test_an_old_off_row_is_off(self):
        self.rows({"at": NOW - 10 * H, "on": True}, {"at": NOW - 2 * H, "on": False})
        self.assertEqual(self.row(), (doctor.LIVE, "off"))

    def test_a_plain_off_row_without_left_on_is_off_even_when_inferred(self):
        self.rows({"at": NOW - 2 * H, "on": False, "inferred": "something else"})
        self.assertEqual(self.row(), (doctor.LIVE, "off"))

    def test_a_poll_that_is_not_fresh_means_pushes_are_not_held(self):
        self.rows({"at": NOW - 4 * H, "on": True})
        self.poll(NOW - sleepmode.POLL_FRESH_S - 60)
        status, reason = self.row()
        self.assertEqual(status, doctor.LIVE)
        self.assertEqual(reason, "on since about four hours ago; the Sleep mode poll is not fresh, so pushes are "
                                 "not held")


class LeftOn(Case):
    def test_the_last_row_an_inferred_off_with_left_on_is_left_on(self):
        self.rows({"at": NOW - 40 * H, "on": True, "rule": "rule-a"},
                  {"at": NOW - 2 * H, "on": False, "inferred": "Sleep left on, owner up", "left_on": "rule-a"})
        self.assertEqual(self.row(), (doctor.STALE, LEFT_ON))

    def test_a_later_on_row_ends_the_left_on_state(self):
        self.rows({"at": NOW - 40 * H, "on": True, "rule": "rule-a"},
                  {"at": NOW - 9 * H, "on": False, "inferred": "Sleep left on, owner up", "left_on": "rule-a"},
                  {"at": NOW - 3 * H, "on": True, "rule": "rule-b"})
        self.assertEqual(self.row(), (doctor.LIVE, "on since about three hours ago"))

    def test_on_far_longer_than_a_night_without_a_close_is_stale_and_held(self):
        self.rows({"at": NOW - (sleepmode.NIGHT_H + 1) * H, "on": True, "rule": "rule-a"})
        self.assertEqual(self.row(), (doctor.STALE, STALE_ON))

    def test_on_just_inside_a_night_is_still_on(self):
        self.rows({"at": NOW - (sleepmode.NIGHT_H - 1) * H, "on": True})
        self.assertEqual(self.row()[0], doctor.LIVE)

    def test_stale_with_a_poll_that_is_not_fresh_says_pushes_are_not_held(self):
        self.rows({"at": NOW - 50 * H, "on": True})
        self.poll(NOW - 50 * H, ok=True)
        self.assertEqual(self.row(), (doctor.STALE, "stale: on far longer than a night; the Sleep mode poll is "
                                                    "not fresh, so pushes are not held"))

    def test_the_night_length_is_a_documented_constant(self):
        self.assertIsInstance(sleepmode.NIGHT_H, float)
        self.assertGreater(sleepmode.NIGHT_H, 8)
        self.assertLess(sleepmode.NIGHT_H, 24)


class Unknown(Case):
    def test_no_file_is_unknown(self):
        self.assertEqual(self.row(), (doctor.MISSING, "unknown: no Sleep mode file in the state dir"))

    def test_no_row_with_a_time_is_unknown(self):
        (self.st / "sleepmode.jsonl").write_text('not json\n{"on": true}\n{"at": "soon", "on": false}\n')
        self.assertEqual(self.row(), (doctor.MISSING, "unknown: no Sleep mode row with a time and an on or off"))

    def test_a_last_row_in_the_future_is_unknown(self):
        self.rows({"at": NOW + 2 * H, "on": True})
        self.assertEqual(self.row(), (doctor.MISSING, "unknown: the last Sleep mode row is timestamped in the "
                                                      "future"))

    def test_an_unreadable_file_is_unknown(self):
        (self.st / "sleepmode.jsonl").mkdir()
        self.assertEqual(self.row(), (doctor.MISSING, "unknown: the Sleep mode file could not be read"))

    def test_broken_lines_are_skipped_and_the_last_good_row_counts(self):
        (self.st / "sleepmode.jsonl").write_text(json.dumps({"at": NOW - 2 * H, "on": False}) + "\n{cut")
        self.assertEqual(self.row(), (doctor.LIVE, "off"))


class Path_(Case):
    def test_limitless_sleepmode_names_the_file_like_kevin_push(self):
        other = Path(self.tmp.name) / "elsewhere" / "sleepmode.jsonl"
        other.parent.mkdir()
        other.write_text(json.dumps({"at": NOW - 2 * H, "on": True}) + "\n")
        (other.parent / "sleepmode-poll.json").write_text(json.dumps({"at": iso(NOW - 60), "ok": True}))
        self.assertEqual(self.row(env={"LIMITLESS_SLEEPMODE": str(other)}),
                         (doctor.LIVE, "on since about two hours ago"))

    def test_the_reason_never_names_the_path_or_the_rule(self):
        self.rows({"at": NOW - 40 * H, "on": True, "rule": "rule-secret"},
                  {"at": NOW - 2 * H, "on": False, "inferred": "Sleep left on, owner up", "left_on": "rule-secret"})
        r = doctor.sleep_mode_row(self.cfg, NOW)
        self.assertNotIn("rule-secret", json.dumps(r))
        self.assertNotIn(str(self.st), json.dumps(r))


class InTheReport(Case):
    def test_the_row_comes_right_after_the_push_sender_row_and_is_read_only(self):
        self.rows({"at": NOW - 2 * H, "on": False})
        before = sorted(p.name for p in self.st.iterdir())
        cfg_path = Path(self.tmp.name) / "config.json"
        cfg_path.write_text(json.dumps(self.cfg))
        with mock.patch.dict(os.environ, {"LIMITLESS_CONFIG": str(cfg_path)}):
            rows = doctor.report(self.cfg, NOW)
        names = [r["name"] for r in rows]
        self.assertEqual(names.index(doctor.SLEEP_MODE_ROW), names.index(doctor.PUSH_SENDER_ROW) + 1)
        self.assertEqual(rows[names.index(doctor.SLEEP_MODE_ROW)]["reason"], "off")
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), before)


class Docs(unittest.TestCase):
    DOC = ROOT / "docs" / "doctor.md"

    def test_the_sleep_mode_example_is_the_scripts_real_output(self):
        import subprocess
        from hermetic_env import child_env
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "sleep_mode_doctor_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        section = self.DOC.read_text().split("## Sleep mode row", 1)[1].split("\n## ", 1)[0]
        self.assertIn("```text\n" + r.stdout + "```", section)
        for words in (LEFT_ON, STALE_ON, "on since", "unknown:", "NIGHT_H", "left_on", "LIMITLESS_SLEEPMODE"):
            self.assertIn(words, section)
        self.assertIsNone(DIGIT.search(r.stdout.replace("sleep_mode_doctor", "")), r.stdout)


if __name__ == "__main__":
    unittest.main()
