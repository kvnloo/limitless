"""limitless/doctor.py: the read-only live-state report. Synthetic state dirs only."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import doctor  # noqa: E402

NOW = 1894708800.0  # 2030-01-15T12:00:00Z, the fixture clock


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
    env.update(extra)
    return env


class DoctorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        self.cfg_path = self.home / "config.json"
        self.cfg = {"state": str(self.st)}

    def write(self, name, data):
        p = self.st / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, (dict, list)):
            data = json.dumps(data)
        p.write_text(data if data.endswith("\n") else data + "\n")
        return p

    def rows(self, cfg=None):
        cfg = self.cfg if cfg is None else cfg
        self.cfg_path.write_text(json.dumps(cfg))
        with mock.patch.dict(os.environ, clean_env(HOME=str(self.home), LIMITLESS_CONFIG=str(self.cfg_path)),
                             clear=True):
            return doctor.report(cfg, NOW)

    def row(self, name, cfg=None):
        rows = self.rows(cfg)
        got = [r for r in rows if r["name"] == name]
        self.assertEqual(len(got), 1, [r["name"] for r in rows])
        return got[0]


class StateDirRow(DoctorCase):
    def test_rows_have_the_three_fields_and_a_known_status(self):
        for r in self.rows():
            self.assertTrue({"name", "status", "reason"} <= set(r), r)
            self.assertIn(r["status"], doctor.STATUSES)

    def test_an_existing_readable_state_dir_is_live(self):
        r = self.row("state dir")
        self.assertEqual(r["status"], "live")
        self.assertEqual(r["reason"], "the state dir exists and is readable")

    def test_a_missing_state_dir_is_missing(self):
        r = self.row("state dir", {"state": str(self.home / "nowhere")})
        self.assertEqual((r["status"], r["reason"]), ("missing", "the state dir does not exist"))

    def test_the_reason_never_names_the_path(self):
        for r in self.rows({"state": str(self.home / "nowhere")}):
            self.assertNotIn(str(self.home), r["reason"])


class InputRows(DoctorCase):
    def setUp(self):
        super().setUp()
        # inputs.json snapshot taken half an hour before NOW: ages grow by that much
        self.write("inputs.json", {"at": "2030-01-15T11:30:00Z",
                                   "ageHours": {"wearable": 3.7, "scale": 51.3, "bike": "down", "anki": None,
                                                "phone": 23.6}})

    def test_a_fresh_input_is_live(self):
        r = self.row("input wearable")
        self.assertEqual((r["kind"], r["status"]), ("input", "live"))
        self.assertEqual(r["reason"], "recording: updated within the last day")

    def test_an_input_over_the_stale_threshold_is_stale(self):
        # under the threshold in the snapshot, over it once the snapshot's own age is added (limitless_status)
        for name in ("input scale", "input phone"):
            r = self.row(name)
            self.assertEqual((r["status"], r["reason"]), ("stale", "not recording: no update for over a day"))

    def test_a_down_input_is_stale(self):
        r = self.row("input bike")
        self.assertEqual((r["status"], r["reason"]), ("stale", "not recording: the sync reports it down"))

    def test_an_input_with_no_age_is_missing(self):
        r = self.row("input anki")
        self.assertEqual((r["status"], r["reason"]), ("missing", "no age for this input in inputs.json"))

    def test_inputs_come_in_name_order_after_the_state_dir(self):
        names = [r["name"] for r in self.rows() if r["kind"] in ("state", "input")]
        self.assertEqual(names, ["state dir", "input anki", "input bike", "input phone", "input scale",
                                 "input wearable"])

    def test_no_inputs_file_is_one_missing_row_with_the_status_tools_reason(self):
        (self.st / "inputs.json").unlink()
        r = self.row("inputs")
        self.assertEqual((r["kind"], r["status"]), ("input", "missing"))
        self.assertEqual(r["reason"], "no inputs.json (with ageHours) in the state dir")


if __name__ == "__main__":
    unittest.main()
