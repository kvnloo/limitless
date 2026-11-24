"""limitless_sleep_coverage: the sleep coverage audit (sleep_coverage.audit) as a tool, read-only.

Label only; counts only under the raw opt-in. Demo-marked sleep file rows never count. No sleep file set, or a
missing one, is value None with a reason that never echoes a path; fewer than a week of known nights is the
label "unknown" with a reason. Synthetic sleep rows and synthetic unlock rows only, a fixed clock.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import doctor, mock_guard, plugin, sleep_coverage as sc, tier_audit, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NAME = "limitless_sleep_coverage"
UTC = timezone.utc
WEST = timezone(timedelta(hours=-6))      # a fixed offset: no DST
TODAY = date(2030, 1, 29)
H = 3600
RAW_KEYS = {"window_nights", "wearable_nights", "proxy_only_nights", "unknown_nights", "known_nights",
            "wearable_share", "target", "goal", "demo_rows"}


def at(day, hour, tz):
    """Epoch seconds of ``hour`` on ``day`` in ``tz`` (None: this machine's zone)."""
    dt = datetime.combine(day, time(0))
    return (dt.replace(tzinfo=tz) if tz is not None else dt).timestamp() + hour * H


def now(tz):
    return at(TODAY, 9, tz)


def night(ago):
    return (TODAY - timedelta(days=ago)).isoformat()


def wear(ago, **extra):
    r = {"night": night(ago), "asleep_s": 7 * H, "source": "synthetic-band"}
    r.update(extra)
    return r


def unlocks(agos, tz, start_h=23, hours=8):
    """Two synthetic unlocks around one quiet span starting at ``start_h`` on each evening ``ago`` nights back."""
    out = []
    for a in agos:
        s = at(TODAY - timedelta(days=a), start_h, tz)
        out += [{"ts": int(s * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"},
                {"ts": int((s + hours * H) * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"}]
    return out


def write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def fill(st, tz):
    """Ten real wearable nights, ten demo-marked ones, the phone on every night of four weeks."""
    rows = [wear(a) for a in range(1, 11)]
    rows += [wear(a, deviceId="demo-strap") for a in range(11, 16)]
    rows += [wear(a, source="synthetic-band-demo") for a in range(16, 21)]
    write(st / "sleep.jsonl", rows)
    write(st / "screen-events.jsonl", unlocks(range(1, 29), tz))


class Tool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        self.reader = StateReader(self.st)
        self.cfg = self.home / "config.json"
        self.config({})
        fill(self.st, UTC)

    def config(self, extra, sleep_file="sleep.jsonl"):
        cfg = dict(extra)
        if sleep_file is not None:
            cfg["sleep_file"] = sleep_file
        self.cfg.write_text(json.dumps(cfg))

    def call(self, raw=False, tz=UTC):
        return tools.sleep_coverage(self.reader, now(tz), raw=raw, env={"LIMITLESS_CONFIG": str(self.cfg)},
                                    home=self.home, tz=tz)

    def test_label_only_without_the_opt_in(self):
        res = self.call()
        self.assertTrue({"value", "modality", "age_h", "evidence_tier"} <= set(res))
        self.assertEqual(set(res["value"]), {"label"})
        self.assertEqual((res["modality"], res["age_h"], res["evidence_tier"]), ("measured", 2.0, "direct"))
        self.assertEqual(res["label"]["tier"], "T1")
        self.assertEqual(res["value"]["label"], res["label"]["label"])
        self.assertEqual(res["label"]["label"], "wearable sleep on some nights, phone estimate on most nights; "
                                                "wearable goal not met; " + mock_guard.LEFT_OUT)
        self.assertEqual(re.findall(r"\d", json.dumps(res["value"])), [])

    def test_counts_only_with_the_raw_opt_in_and_demo_rows_never_count(self):
        v = self.call(raw=True)["value"]
        self.assertEqual(set(v) - {"label"}, RAW_KEYS)
        self.assertEqual((v["wearable_nights"], v["proxy_only_nights"], v["unknown_nights"]), (10, 18, 0))
        self.assertEqual((v["window_nights"], v["known_nights"], v["demo_rows"]), (28, 28, 10))
        self.assertEqual((v["target"], v["goal"]), (0.8, "not met"))

    def test_window_and_target_come_from_config(self):
        self.config({"sleep_coverage_days": 10, "sleep_coverage_target": 0.9})
        v = self.call(raw=True)["value"]
        self.assertEqual((v["window_nights"], v["wearable_nights"], v["target"], v["goal"]), (10, 10, 0.9, "met"))
        self.assertEqual(v["label"], "wearable sleep on every night; wearable goal met")

    def test_the_proxy_alone_is_never_wearable(self):
        write(self.st / "sleep.jsonl", [])
        res = self.call(raw=True)
        self.assertEqual((res["value"]["wearable_nights"], res["value"]["proxy_only_nights"]), (0, 28))
        self.assertEqual(res["modality"], "proxy")
        self.assertEqual(res["evidence_tier"], "indirect")
        self.assertEqual(res["label"]["label"], "no wearable sleep, phone estimate on every night; wearable goal not met")

    def test_only_demo_rows_and_no_phone_is_no_wearable_night(self):
        write(self.st / "sleep.jsonl", [wear(a, device="Synthetic Band (demo)") for a in range(1, 29)])
        (self.st / "screen-events.jsonl").unlink()
        res = self.call()
        self.assertIsNone(res["value"])
        self.assertEqual((res["reason"], res["label"]["label"]), (sc.NO_NIGHTS_REASON, "unknown"))

    def test_a_missing_sleep_file_is_unknown_with_a_path_free_reason(self):
        (self.st / "sleep.jsonl").unlink()
        res = self.call()
        self.assertIsNone(res["value"])
        self.assertEqual(res["evidence_tier"], "none")
        self.assertEqual((res["reason"], res["label"]["label"]), (sc.UNREADABLE_REASON, "unknown"))
        self.assertNotIn(str(self.home), json.dumps(res))
        self.assertNotIn("sleep.jsonl", json.dumps(res))

    def test_no_sleep_file_set_is_unknown_with_a_reason(self):
        self.config({}, sleep_file=None)
        res = self.call()
        self.assertIsNone(res["value"])
        self.assertEqual((res["reason"], res["label"]["label"]), (sc.NO_FILE_REASON, "unknown"))
        self.assertNotIn(str(self.home), json.dumps(res))

    def test_fewer_than_a_week_of_known_nights_is_unknown(self):
        write(self.st / "sleep.jsonl", [wear(a) for a in range(1, 7)])
        (self.st / "screen-events.jsonl").unlink()
        res = self.call(raw=True)
        self.assertIsNone(res["value"])
        self.assertEqual((res["reason"], res["label"]["label"]), (sc.FEW_KNOWN_REASON, "unknown"))

    def test_whole_night_gaps_are_unknown_not_zero(self):
        write(self.st / "sleep.jsonl", [wear(a) for a in range(1, 21)])
        write(self.st / "screen-events.jsonl", unlocks(range(1, 23), UTC))
        v = self.call(raw=True)["value"]
        self.assertEqual((v["wearable_nights"], v["proxy_only_nights"], v["unknown_nights"]), (20, 2, 6))
        self.assertEqual(v["goal"], "unknown")

    def test_a_non_utc_zone_reads_its_own_evenings(self):
        write(self.st / "sleep.jsonl", [])
        write(self.st / "screen-events.jsonl", unlocks(range(1, 29), WEST, start_h=20))
        west = self.call(raw=True, tz=WEST)["value"]
        self.assertEqual(west["proxy_only_nights"], 28)
        utc = tools.sleep_coverage(self.reader, now(WEST), raw=True, env={"LIMITLESS_CONFIG": str(self.cfg)},
                                   home=self.home, tz=UTC)
        self.assertIsNone(utc["value"])               # 20:00 at UTC-6 is early morning in UTC: no night's
        self.assertEqual(utc["reason"], sc.NO_NIGHTS_REASON)

    def test_nothing_is_written(self):
        before = sorted((p.name, p.read_bytes()) for p in self.st.iterdir())
        self.call(raw=True)
        self.assertEqual(sorted((p.name, p.read_bytes()) for p in self.st.iterdir()), before)


class Wiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        fill(self.home, None)
        self.cfg = self.home / "config.json"
        self.cfg.write_text(json.dumps({"sleep_file": "sleep.jsonl"}))

    def env(self, **extra):
        return dict({"LIMITLESS_STATE": str(self.home), "LIMITLESS_CONFIG": str(self.cfg)}, **extra)

    def handler(self):
        return json.loads(plugin._handler(plugin.TOOLS[NAME][1], NAME)({}))

    def test_through_the_plugin_handler_counts_need_the_opt_in(self):
        with mock.patch.dict(os.environ, self.env(), clear=True), mock.patch("time.time", return_value=now(None)):
            res = self.handler()
        self.assertEqual(set(res["value"]), {"label"})
        with mock.patch.dict(os.environ, self.env(LIMITLESS_RAW_IN_PROMPT="1"), clear=True), \
                mock.patch("time.time", return_value=now(None)):
            res = self.handler()
        self.assertEqual((res["value"]["wearable_nights"], res["value"]["demo_rows"]), (10, 10))

    def test_the_result_passes_the_tier_audit_as_t1(self):
        log = self.home / "audit.jsonl"
        with mock.patch.dict(os.environ, self.env(**{tier_audit.ENV_KEY: str(log)}), clear=True), \
                mock.patch("time.time", return_value=now(None)):
            res = self.handler()
        (row,) = [json.loads(ln) for ln in log.read_text().splitlines()]
        self.assertEqual((row["hook"], row["tier"], row["digits"], row["blocked"], row["opt_in"]),
                         ("tool:" + NAME, "T1", 0, False, False))
        self.assertIn("wearable goal not met", res["label"]["label"])
        got = tier_audit.audit_result("tool:" + NAME, res, False)
        self.assertEqual(got, res)

    def test_manifest_lists_the_tool(self):
        self.assertIn("  - " + NAME + "\n", (ROOT / "plugin.yaml").read_text())
        self.assertIn(NAME, doctor.manifest_tools())

    def test_doctor_tool_row(self):
        with mock.patch.dict(os.environ, self.env(), clear=True):
            r = doctor.tool_row(NAME, now(None))
        self.assertEqual(r["status"], "live")
        (self.home / "sleep.jsonl").unlink()
        with mock.patch.dict(os.environ, self.env(), clear=True):
            r = doctor.tool_row(NAME, now(None))
        self.assertEqual((r["status"], r["reason"]), ("missing", sc.UNREADABLE_REASON))


if __name__ == "__main__":
    unittest.main()
