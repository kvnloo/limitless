"""limitless_presleep_hr: the pre-sleep heart rate as an evidence envelope, a digit-free label by default.

Synthetic rows only. The beats per minute appear only under LIMITLESS_RAW_IN_PROMPT=1, the same opt-in the
state card uses. No file, no row, phone-only rows or too few nights is value None with a reason: unknown,
never zero.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import plugin, presleep_hr, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_plugin import FakeCtx, manifest_list  # noqa: E402

TODAY = date(2030, 1, 28)
NOW = datetime.combine(TODAY, time(9)).timestamp()   # local morning, as plugin's date.fromtimestamp reads it
FIELDS = {"value", "modality", "age_h", "evidence_tier"}


def rows(last=70.0, n=14, usual=60.0, modality="measured"):
    out = [{"night": (TODAY - timedelta(days=b)).isoformat(), "bpm": usual, "modality": modality}
           for b in range(n + 1, 1, -1)]
    return out + [{"night": (TODAY - timedelta(days=1)).isoformat(), "bpm": last, "modality": modality}]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_STATE": str(self.st)}

    def configure(self, data=None, name="presleep-hr.jsonl"):
        self.cfg.write_text(json.dumps({"presleep_hr_file": name}))
        if data is not None:
            (self.st / name).write_text("".join(json.dumps(r) + "\n" for r in data))

    def tool(self, raw=False):
        return tools.presleep_hr(StateReader(self.st), NOW, raw=raw, env=self.env)


class Reader(Base):
    def test_no_config_is_no_file_and_no_rows(self):
        self.assertIsNone(StateReader(self.st).presleep_hr_file(self.env))
        self.assertEqual(StateReader(self.st).presleep_hr_rows(self.env), [])

    def test_a_relative_path_is_in_the_state_dir_and_bad_lines_are_skipped(self):
        self.configure()
        (self.st / "presleep-hr.jsonl").write_text('{"night": "2030-01-27", "bpm": 61, "modality": "measured"}\n'
                                                   'not json\n[1]\n')
        r = StateReader(self.st)
        self.assertEqual(r.presleep_hr_file(self.env), self.st / "presleep-hr.jsonl")
        self.assertEqual(r.presleep_hr_rows(self.env), [{"night": "2030-01-27", "bpm": 61, "modality": "measured"}])

    def test_a_missing_file_is_no_rows(self):
        self.configure()
        self.assertEqual(StateReader(self.st).presleep_hr_rows(self.env), [])


class Tool(Base):
    def test_no_file_configured_is_missing_with_a_reason_naming_the_key(self):
        got = self.tool()
        self.assertIsNone(got["value"])
        self.assertIn("presleep_hr_file", got["reason"])
        self.assertEqual(got["evidence_tier"], "none")

    def test_known_is_a_label_only_envelope(self):
        self.configure(rows(last=70.0))
        got = self.tool()
        self.assertTrue(FIELDS <= set(got))
        self.assertEqual(got["value"], {"label": "pre-sleep heart rate higher than usual (wearable)"})
        self.assertEqual(got["modality"], "measured")
        self.assertEqual(got["evidence_tier"], "direct")
        self.assertEqual(got["age_h"], 9.0)
        self.assertEqual(got["label"], {"label": "pre-sleep heart rate higher than usual (wearable)", "tier": "T1",
                                        "modality": "measured"})
        text = json.dumps({k: v for k, v in got.items() if k != "age_h"})
        self.assertEqual(re.findall(r"\d", text.replace("T1", "")), [], text)

    def test_raw_numbers_only_with_the_opt_in(self):
        self.configure(rows(last=70.0))
        got = self.tool(raw=True)
        self.assertEqual(got["value"]["bpm"], 70.0)
        self.assertEqual(got["value"]["baseline_bpm"], 60.0)
        self.assertEqual(got["value"]["baseline_nights"], 14)
        self.assertEqual(got["value"]["night"], (TODAY - timedelta(days=1)).isoformat())
        self.assertNotIn("bpm", self.tool()["value"])

    def test_unknown_is_value_none_with_the_plain_reason(self):
        for data, reason in ((rows(n=3), presleep_hr.TOO_FEW), (rows(modality="proxy"), presleep_hr.PHONE_ONLY),
                             ([{"night": "2030-01-27", "bpm": 0, "modality": "measured"}], presleep_hr.NO_WEARABLE)):
            self.configure(data)
            got = self.tool(raw=True)
            self.assertIsNone(got["value"], data)
            self.assertEqual(got["reason"], reason)
            self.assertEqual(got["evidence_tier"], "none")
            self.assertNotIn("label", got)

    def test_stale_is_unknown(self):
        old = [dict(r, night=(date.fromisoformat(r["night"]) - timedelta(days=3)).isoformat()) for r in rows()]
        self.configure(old)
        got = self.tool()
        self.assertIsNone(got["value"])
        self.assertEqual(got["reason"], presleep_hr.STALE)
        self.assertGreater(got["age_h"], presleep_hr.MAX_AGE_H)


class Plugin(Base):
    def call(self, raw=None):
        ctx = FakeCtx()
        plugin.register(ctx)
        env = dict(self.env)
        if raw:
            env["LIMITLESS_RAW_IN_PROMPT"] = "1"
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("time.time", return_value=NOW):
            return json.loads(ctx.tools["limitless_presleep_hr"]["handler"]({}, task_id="t"))

    def test_registered_and_in_the_manifest(self):
        self.assertIn("limitless_presleep_hr", plugin.TOOLS)
        self.assertIn("limitless_presleep_hr", manifest_list("provides_tools"))
        desc = plugin.TOOLS["limitless_presleep_hr"][0]["description"]
        for word in ("wearable", "raw opt-in", "never"):
            self.assertIn(word, desc)

    def test_the_handler_keeps_numbers_behind_the_opt_in(self):
        self.configure(rows(last=50.0))
        got = self.call()
        self.assertEqual(got["value"], {"label": "pre-sleep heart rate lower than usual (wearable)"})
        self.assertEqual(self.call(raw=True)["value"]["bpm"], 50.0)


if __name__ == "__main__":
    unittest.main()
