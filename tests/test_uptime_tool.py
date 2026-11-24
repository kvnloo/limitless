"""limitless_uptime: the uptime audit (uptime_audit.audit) of the sync's runs.jsonl as a tool, read-only.

Label only; counts only under the raw opt-in. No runs.jsonl, or no run in the window, is value None with a
reason (unknown, not zero); fewer than a week of known days is the label "unknown" with a reason. Reasons never
echo a path. Synthetic rows in the sync's shape, a fixed clock. Nothing is written or sent.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import doctor, plugin, tier_audit, tools, uptime_audit as ua  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NOW = 1894708800.0                       # synthetic clock: midday UTC
H, D = 3600.0, 86400.0
UTC = timezone.utc
NAME = "limitless_uptime"


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(t, stale=None):
    r = {"at": iso(t), "job": "sync", "ok": True}
    if stale is not None:
        r["inputs"] = "stale " + ",".join(stale)
    return r


def write(st, rows, extra=""):
    (st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + extra)


def inputs_json(st, names):
    (st / "inputs.json").write_text(json.dumps({"at": iso(NOW - H), "ageHours": {n: 1.0 for n in names}}))


def month(stale_by_day=lambda n: ["whoop"]):
    """One run a day for 28 days, the newest two hours before NOW."""
    return [run(NOW - 2 * H - n * D, stale_by_day(n)) for n in range(28)]


class Tool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        self.reader = StateReader(self.st)
        inputs_json(self.st, ["phoneApps", "whoop", "desktopAW"])
        write(self.st, month(), extra="torn line\n")
        self.cfg = self.home / "config.json"
        self.config({})

    def config(self, cfg):
        self.cfg.write_text(json.dumps(cfg))

    def call(self, raw=False):
        return tools.uptime(self.reader, NOW, raw=raw, env={"LIMITLESS_CONFIG": str(self.cfg)}, home=self.home,
                            tz=UTC)

    def test_label_only_without_the_opt_in(self):
        res = self.call()
        self.assertTrue({"value", "modality", "age_h", "evidence_tier"} <= set(res))
        self.assertEqual(set(res["value"]), {"label"})
        self.assertEqual(res["modality"], "measured")
        self.assertEqual(res["age_h"], 2.0)
        self.assertEqual(res["evidence_tier"], "direct")
        self.assertEqual(res["label"]["tier"], "T1")
        self.assertEqual(res["value"]["label"], res["label"]["label"])
        self.assertEqual(res["label"]["label"],
                         "phone apps and desktop AW fresh every day; whoop stale all month; uptime goal not met")
        self.assertFalse(any(c.isdigit() for c in json.dumps(res["value"])))

    def test_counts_only_with_the_raw_opt_in(self):
        v = self.call(raw=True)["value"]
        self.assertEqual(v["inputs"]["whoop"], {"fresh": 0, "stale": 28, "unknown": 0})
        self.assertEqual(v["inputs"]["phoneApps"], {"fresh": 28, "stale": 0, "unknown": 0})
        self.assertEqual((v["known_days"], v["all_fresh_days"], v["window_days"]), (28, 0, 28))
        self.assertEqual((v["target"], v["goal"], v["skipped"]), (0.95, "not met", 1))
        self.assertEqual(len(v["days"]), 28)

    def test_outage_ignore_and_the_window_come_from_config(self):
        self.config({"outage_ignore": ["whoop"], "uptime_days": 14, "uptime_target": 0.9})
        res = self.call(raw=True)
        self.assertEqual(sorted(res["value"]["inputs"]), ["desktopAW", "phoneApps"])
        self.assertEqual((res["value"]["window_days"], res["value"]["target"]), (14, 0.9))
        self.assertEqual(res["label"]["label"], "phone apps and desktop AW fresh every day; uptime goal met")

    def test_old_rows_without_inputs_are_unknown_with_a_reason(self):
        write(self.st, [run(NOW - 2 * H - n * D) for n in range(28)] + month()[:6])
        res = self.call(raw=True)
        self.assertIsNone(res["value"])
        self.assertEqual(res["evidence_tier"], "none")
        self.assertEqual(res["label"]["label"], "unknown")
        self.assertEqual(res["reason"], ua.FEW_KNOWN_REASON)
        self.assertEqual(doctor.classify(NAME, res)[0], doctor.MISSING)

    def test_no_run_log_is_unknown_not_zero_and_never_echoes_a_path(self):
        (self.st / "runs.jsonl").unlink()
        res = self.call()
        self.assertIsNone(res["value"])
        self.assertEqual(res["evidence_tier"], "none")
        self.assertEqual(res["reason"], ua.NO_LOG_REASON)
        self.assertEqual(res["label"]["label"], "unknown")
        self.assertNotIn(str(self.home), json.dumps(res))

    def test_no_run_in_the_window_is_unknown(self):
        write(self.st, [run(NOW - 60 * D, ["whoop"])])
        res = self.call()
        self.assertIsNone(res["value"])
        self.assertEqual(res["reason"], ua.NO_ROWS_REASON)

    def test_a_non_utc_zone_reads_local_days(self):
        west = timezone(timedelta(hours=-6))
        write(self.st, [run(NOW - 11 * H - n * D, ["whoop"]) for n in range(10)])   # 01:00Z: 19:00 the day before
        res = tools.uptime(self.reader, NOW, raw=True, env={"LIMITLESS_CONFIG": str(self.cfg)}, home=self.home,
                           tz=west)
        self.assertEqual(res["value"]["days"][-1]["day"], "2030-01-15")
        self.assertIsNone(res["value"]["days"][-1]["stale"])       # today at -6 has no run yet
        self.assertEqual(res["value"]["inputs"]["whoop"]["stale"], 10)

    def test_nothing_is_written(self):
        before = sorted(p.name for p in self.st.iterdir())
        text = (self.st / "runs.jsonl").read_text()
        self.call(raw=True)
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), before)
        self.assertEqual((self.st / "runs.jsonl").read_text(), text)


class Wiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        inputs_json(self.home, ["phoneApps", "whoop"])
        write(self.home, month())
        self.cfg = self.home / "config.json"
        self.cfg.write_text(json.dumps({}))

    def env(self, **extra):
        return dict({"LIMITLESS_STATE": str(self.home), "LIMITLESS_CONFIG": str(self.cfg)}, **extra)

    def handler(self):
        return json.loads(plugin._handler(plugin.TOOLS[NAME][1], NAME)({}))

    def test_through_the_plugin_handler_counts_need_the_opt_in(self):
        with mock.patch.dict(os.environ, self.env(), clear=True), mock.patch("time.time", return_value=NOW):
            res = self.handler()
        self.assertEqual(set(res["value"]), {"label"})
        with mock.patch.dict(os.environ, self.env(LIMITLESS_RAW_IN_PROMPT="1"), clear=True), \
                mock.patch("time.time", return_value=NOW):
            res = self.handler()
        self.assertEqual(res["value"]["inputs"]["whoop"]["stale"], 28)

    def test_the_result_passes_the_tier_audit_as_t1(self):
        log = self.home / "audit.jsonl"
        with mock.patch.dict(os.environ, self.env(**{tier_audit.ENV_KEY: str(log)}), clear=True), \
                mock.patch("time.time", return_value=NOW):
            res = self.handler()
        (row,) = [json.loads(ln) for ln in log.read_text().splitlines()]
        self.assertEqual((row["hook"], row["tier"], row["digits"], row["blocked"], row["opt_in"]),
                         ("tool:" + NAME, "T1", 0, False, False))
        self.assertIn("whoop stale all month", res["label"]["label"])
        self.assertNotIn("whoop", log.read_text())

    def test_manifest_lists_the_tool(self):
        self.assertIn("  - " + NAME + "\n", (ROOT / "plugin.yaml").read_text())

    def test_doctor_tool_row(self):
        with mock.patch.dict(os.environ, self.env(), clear=True):
            r = doctor.tool_row(NAME, NOW)
        self.assertEqual(r["status"], "live")
        (self.home / "runs.jsonl").unlink()
        with mock.patch.dict(os.environ, self.env(), clear=True):
            r = doctor.tool_row(NAME, NOW)
        self.assertEqual((r["status"], r["reason"]), ("missing", ua.NO_LOG_REASON))


if __name__ == "__main__":
    unittest.main()
