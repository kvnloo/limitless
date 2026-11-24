"""limitless_delivery: the delivery audit (delivery_audit.audit) of the push log as a tool, read-only.

Label only; counts only under the raw opt-in. Config push_log unset is value None with a reason (unknown, not
zero); reasons never echo a path. Synthetic rows in bin/kevin-push's log shape, a fixed clock. Nothing is
written or sent.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import delivery_audit as da, doctor, jobs, plugin, send_gate, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NOW = 1894708800.0                       # synthetic clock
H = 3600.0


def row(at, how="telegram", title="Pick one", body="Keep the loop?\nReply: Yes / No\nWhy now: you woke up"):
    return {"at": int(at), "tag": "x", "cls": "decision", "title": title, "body": body, "how": how}


class Tool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        self.reader = StateReader(self.st)
        self.log = self.st / "push-log.jsonl"
        rows = [row(NOW - 2 * H), row(NOW - 3 * H, title=jobs.WAKE_BRIEF.send_title, body="Good morning."),
                row(NOW - 4 * H, how="held (sleep mode)"), row(NOW - 30 * H)]
        self.log.write_text("".join(json.dumps(r) + "\n" for r in rows) + "broken line\n")
        self.cfg = self.home / "config.json"
        self.cfg.write_text(json.dumps({"push_log": "push-log.jsonl"}))
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}

    def call(self, raw=False, env=None):
        return tools.delivery(self.reader, NOW, raw=raw, env=env or self.env, home=self.home)

    def test_label_only_without_the_opt_in(self):
        res = self.call()
        self.assertTrue({"value", "modality", "age_h", "evidence_tier"} <= set(res))
        self.assertEqual(set(res["value"]), {"label"})
        self.assertEqual(res["modality"], "measured")
        self.assertEqual(res["age_h"], 2.0)
        self.assertEqual(res["evidence_tier"], "direct")
        self.assertEqual(res["label"]["tier"], "T1")
        self.assertEqual(res["value"]["label"], res["label"]["label"])
        self.assertIn("within the push limit on every logged day", res["label"]["label"])
        self.assertFalse(any(c.isdigit() for c in json.dumps(res["value"])))

    def test_counts_only_with_the_raw_opt_in(self):
        v = self.call(raw=True)["value"]
        self.assertEqual(v["delivered"], 3)
        self.assertEqual(v["skipped"], 1)
        self.assertEqual(v["cap"], send_gate.DAILY_CAP)
        self.assertEqual(v["no_action"], 1)
        self.assertEqual(len(v["days"]), da.DAYS)

    def test_no_push_log_set_is_unknown_not_zero(self):
        self.cfg.write_text(json.dumps({}))
        res = self.call()
        self.assertIsNone(res["value"])
        self.assertEqual(res["evidence_tier"], "none")
        self.assertEqual(res["reason"], "no push log set (config push_log)")
        self.assertEqual(res["label"]["label"], "unknown: no push log set")

    def test_a_missing_log_says_so_without_the_path(self):
        self.cfg.write_text(json.dumps({"push_log": str(self.home / "secret-dir" / "nope.jsonl")}))
        res = self.call()
        self.assertIsNone(res["value"])
        self.assertNotIn("secret-dir", json.dumps(res))
        self.assertNotIn(str(self.home), json.dumps(res))

    def test_a_log_with_no_row_this_week_is_unknown(self):
        self.log.write_text(json.dumps(row(NOW - 30 * 24 * H)) + "\n")
        res = self.call()
        self.assertIsNone(res["value"])
        self.assertEqual(res["reason"], "no push row in the last seven days")

    def test_push_cap_comes_from_config(self):
        self.cfg.write_text(json.dumps({"push_log": "push-log.jsonl", "push_cap": 1}))
        v = self.call(raw=True)["value"]
        self.assertEqual(v["cap"], 1)
        self.assertEqual(len(v["over_cap_days"]), 1)

    def test_wake_days_come_from_the_plugins_wake_events(self):
        day = datetime.fromtimestamp(NOW - 3 * H).date().isoformat()
        evs = [{"event": "wake", "at": NOW - 3 * H - 60}]
        with mock.patch("limitless.jobs_runner.events", return_value=evs):
            v = self.call(raw=True)["value"]
        self.assertEqual(v["wake"]["wake_days"], 1)
        self.assertEqual(v["wake"]["brief_delivered"], 1)
        self.assertTrue(next(d for d in v["days"] if d["day"] == day)["wake_day"])

    def test_nothing_is_written(self):
        before = sorted(p.name for p in self.st.iterdir())
        text = self.log.read_text()
        self.call(raw=True)
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), before)
        self.assertEqual(self.log.read_text(), text)


class Wiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        (self.home / "log.jsonl").write_text(json.dumps(row(NOW - H)) + "\n")
        self.cfg = self.home / "config.json"

    def env(self, cfg, **extra):
        self.cfg.write_text(json.dumps(cfg))
        return dict({"LIMITLESS_STATE": str(self.home), "LIMITLESS_CONFIG": str(self.cfg)}, **extra)

    def handler(self):
        return json.loads(plugin._handler(plugin.TOOLS["limitless_delivery"][1], "limitless_delivery")({}))

    def test_through_the_plugin_handler_counts_need_the_opt_in(self):
        with mock.patch.dict(os.environ, self.env({"push_log": "log.jsonl"}), clear=True), \
                mock.patch("time.time", return_value=NOW):
            res = self.handler()
        self.assertEqual(set(res["value"]), {"label"})
        with mock.patch.dict(os.environ, self.env({"push_log": "log.jsonl"}, LIMITLESS_RAW_IN_PROMPT="1"),
                             clear=True), mock.patch("time.time", return_value=NOW):
            res = self.handler()
        self.assertEqual(res["value"]["delivered"], 1)

    def test_manifest_lists_the_tool(self):
        self.assertIn("  - limitless_delivery\n", (ROOT / "plugin.yaml").read_text())

    def test_doctor_row_is_off_without_a_push_log_and_live_with_one(self):
        with mock.patch.dict(os.environ, self.env({}), clear=True):
            r = doctor.tool_row("limitless_delivery", NOW)
        self.assertEqual((r["status"], r["reason"]), ("off", "no push log set (config push_log)"))
        with mock.patch.dict(os.environ, self.env({"push_log": "log.jsonl"}), clear=True):
            r = doctor.tool_row("limitless_delivery", NOW)
        self.assertEqual(r["status"], "live")


if __name__ == "__main__":
    unittest.main()
