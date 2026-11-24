"""limitless_naps: yesterday's naps in words, an evidence envelope, read-only. Synthetic state only."""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from limitless import plugin, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

UTC = timezone.utc
TODAY = date(2030, 3, 12)
NOW = datetime(2030, 3, 12, 7, 30, tzinfo=UTC).timestamp()
FIELDS = {"value", "modality", "age_h", "evidence_tier"}


def iso(d, hh, mm=0):
    return datetime.combine(d, time(hh, mm), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


Y = TODAY - timedelta(days=1)
ROWS = [(Y - timedelta(days=1), 23, 0, True), (Y, 7, 0, False), (Y, 20, 0, True), (Y, 20, 40, False),
        (Y, 23, 0, True), (TODAY, 7, 0, False)]


def write(st: Path, rows):
    st.mkdir(parents=True, exist_ok=True)
    (st / "sleepmode.jsonl").write_text("".join(json.dumps({"at": iso(d, h, m), "on": o}) + "\n"
                                                for d, h, m, o in rows))


class Tool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name) / "st"
        self.env = {"LIMITLESS_CONFIG": str(Path(self.tmp.name) / "none.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, raw=False, cfg=None):
        if cfg is not None:
            Path(self.env["LIMITLESS_CONFIG"]).write_text(json.dumps(cfg))
        return tools.naps(StateReader(self.st), NOW, TODAY, raw=raw, env=self.env, tz=UTC)

    def test_envelope_with_words_only(self):
        write(self.st, ROWS)
        res = self.call()
        self.assertTrue(FIELDS <= set(res), res)
        self.assertEqual(res["value"], {"label": "naps yesterday: one short nap, close to the night"})
        self.assertEqual(res["modality"], "proxy")
        self.assertEqual(res["evidence_tier"], "indirect")
        self.assertEqual(res["age_h"], 0.5)
        self.assertEqual(res["label"], {"label": "naps yesterday: one short nap, close to the night",
                                        "tier": "T1", "modality": "proxy"})
        self.assertEqual(re.findall(r"\d", json.dumps(res["value"])), [])

    def test_raw_opt_in_adds_start_and_end(self):
        write(self.st, ROWS)
        res = self.call(raw=True)
        nap = datetime(2030, 3, 11, 20, tzinfo=UTC).timestamp()
        self.assertEqual(res["value"]["naps"], [{"start_s": nap, "end_s": nap + 2400}])
        self.assertEqual(res["value"]["close"], 1)

    def test_config_nap_max_h_is_read(self):
        write(self.st, ROWS[:2] + [(Y, 13, 0, True), (Y, 15, 30, False)] + ROWS[4:])
        self.assertEqual(self.call()["value"]["label"], "naps yesterday: none")
        self.assertEqual(self.call(cfg={"nap_max_h": 3})["value"]["label"], "naps yesterday: one short nap")

    def test_unknown_is_a_null_value_with_reason_never_zero(self):
        write(self.st, [(TODAY, 7, 0, False)])
        res = self.call()
        self.assertIsNone(res["value"])
        self.assertEqual(res["evidence_tier"], "none")
        self.assertIn("no phone Sleep-mode change", res["reason"])
        self.assertEqual(res["label"]["label"], "naps yesterday: unknown")

    def test_no_file_is_unknown_and_writes_nothing(self):
        self.st.mkdir()
        res = self.call()
        self.assertIsNone(res["value"])
        self.assertEqual(list(self.st.iterdir()), [])


class Plugin(unittest.TestCase):
    def test_registered_with_a_schema(self):
        schema, fn, emoji = plugin.TOOLS["limitless_naps"]
        self.assertEqual(schema["name"], "limitless_naps")
        for word in ("Sleep mode", "proxy", "close to the night", "raw opt-in", "Read-only"):
            self.assertIn(word, schema["description"])
        for bad in ("should", "target", "streak"):
            self.assertNotIn(bad, schema["description"].replace("no target", "").replace("no streak", ""))

    def test_handler_returns_the_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = Path(tmp) / "st"
            today = date.fromtimestamp(NOW)
            y = today - timedelta(days=1)
            local = lambda d, h, m=0: datetime.combine(d, time(h, m)).timestamp()   # noqa: E731 - local zone
            st.mkdir()
            rows = [(local(y - timedelta(days=1), 23), True), (local(y, 7), False), (local(y, 13), True),
                    (local(y, 13, 30), False), (local(y, 23), True), (local(today, 6), False)]
            (st / "sleepmode.jsonl").write_text("".join(json.dumps({"at": t, "on": o}) + "\n" for t, o in rows))
            env = {"LIMITLESS_STATE": str(st), "LIMITLESS_CONFIG": str(Path(tmp) / "none.json")}
            with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=NOW):
                os.environ.pop("LIMITLESS_RAW_IN_PROMPT", None)
                res = json.loads(plugin._handler(plugin.TOOLS["limitless_naps"][1], "limitless_naps")({}))
        self.assertEqual(res["value"], {"label": "naps yesterday: one short nap"})
        self.assertEqual(res["label"]["tier"], "T1")


if __name__ == "__main__":
    unittest.main()
