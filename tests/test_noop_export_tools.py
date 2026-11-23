"""What limitless-noop-export writes reaches limitless_sleep and limitless_presleep_hr as wearable answers, and
nothing that identifies a person or a device leaves the NOOP DB.

Synthetic DBs only (tests/noop_fixture.py); the planted name, device name and serial-like strings are made up.
Times are local, as the plugin's handlers read them. Nothing here sends.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import noop_export as nx, plugin, presleep_hr  # noqa: E402
from noop_fixture import RING, hr_before, make_db, stages  # noqa: E402
from test_plugin import FakeCtx  # noqa: E402

TODAY = date(2030, 1, 28)
NOW = datetime.combine(TODAY, time(9)).timestamp()   # local morning, as the handlers' date.fromtimestamp reads it
H = 3600
NAME = "Alexandra Placeholder"
DEVICE = "Synthetic Ring Model Q"
SERIAL = "SN-QX7Z9K4M2P"
MAC = "0A:1B:2C:3D:4E:5F"
DEVICE_ID = "ring-" + SERIAL


def local(d, hh):
    return int(datetime.combine(d, time(hh)).timestamp())


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.cfg = self.dir / "config.json"
        self.cfg.write_text(json.dumps({"noop_db": "noop.db", "sleep_file": "sleep.jsonl",
                                        "presleep_hr_file": "presleep-hr.jsonl"}))
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_STATE": str(self.st)}

    def db(self, last_night, n=15, device=RING, devices=None, extra=None):
        sessions, hr = [], []
        for i in range(n):
            d = last_night - timedelta(days=n - 1 - i)
            on = local(d, 23)
            sessions.append((device, on, on + 8 * H, 0.9, stages(on, 7 * H, H)))
            hr += hr_before(device, on, 60 + (i % 2))
        make_db(self.st / "noop.db", sessions=sessions, hr=hr, devices=devices)
        if extra:
            extra(self.st / "noop.db")

    def export(self):
        out, err = io.StringIO(), io.StringIO()
        code = nx.main(["--write"], env=self.env, home=self.dir, out=out, err=err)
        self.assertEqual((code, err.getvalue()), (0, ""))
        return out.getvalue()

    def call(self, name):
        with mock.patch.dict(os.environ, self.env), mock.patch("time.time", return_value=NOW):
            ctx = FakeCtx()
            plugin.register(ctx)
            return json.loads(ctx.tools[name]["handler"]({}))


class Tools(Base):
    def test_fresh_nights_are_wearable_answers_not_the_proxy(self):
        self.db(TODAY - timedelta(days=1))
        self.export()
        s = self.call("limitless_sleep")
        self.assertEqual(s["modality"], "measured")
        self.assertEqual(s["value"]["wearable_nights"], 7)
        self.assertTrue(s["value"]["label"].startswith("sleep: wearable on most nights"), s["value"]["label"])
        p = self.call("limitless_presleep_hr")
        self.assertEqual(p["modality"], "measured")
        self.assertIsNotNone(p["value"], p)
        self.assertIn(p["value"]["label"], presleep_hr.LABELS[:3])
        self.assertTrue(p["value"]["label"].endswith("(wearable)"))

    def test_only_stale_nights_still_say_stale(self):
        self.db(TODAY - timedelta(days=10))
        self.export()
        s = self.call("limitless_sleep")
        self.assertEqual(s["modality"], "proxy")
        self.assertEqual(s["value"]["wearable_nights"], 0)
        self.assertGreater(s["age_h"], 36)
        self.assertTrue(s["value"]["label"].startswith("sleep: wearable on no nights"), s["value"]["label"])
        p = self.call("limitless_presleep_hr")
        self.assertIsNone(p["value"])
        self.assertEqual(p["reason"], presleep_hr.STALE)


class Privacy(Base):
    def test_no_name_device_serial_or_id_reaches_the_files_or_stdout(self):
        devices = [{"id": DEVICE_ID, "brand": DEVICE, "model": DEVICE, "nickname": NAME, "peripheralId": MAC,
                    "sourceKind": "oura", "capabilities": "hr,sleep", "status": "active", "addedAt": 0,
                    "lastSeenAt": 0}]

        def plant(path):
            import sqlite3
            con = sqlite3.connect(str(path))
            con.execute("INSERT INTO device (id, mac, name) VALUES (?, ?, ?)", (DEVICE_ID, MAC, NAME + "'s " + DEVICE))
            con.commit()
            con.close()

        self.db(TODAY - timedelta(days=1), device=DEVICE_ID, devices=devices, extra=plant)
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(nx.main([], env=self.env, home=self.dir, out=out, err=err), 0)
        printed = out.getvalue() + err.getvalue() + self.export()
        files = (self.st / "sleep.jsonl").read_text() + (self.st / "presleep-hr.jsonl").read_text()
        self.assertEqual(len(files.splitlines()), 30)
        for secret in (NAME, "Alexandra", DEVICE, SERIAL, MAC, DEVICE_ID, "oura", "ring"):
            self.assertNotIn(secret.lower(), (printed + files).lower(), secret)
        for ln in (self.st / "sleep.jsonl").read_text().splitlines():
            self.assertEqual(sorted(json.loads(ln)), ["asleep_s", "end", "night", "source", "start"])
        for ln in (self.st / "presleep-hr.jsonl").read_text().splitlines():
            self.assertEqual(sorted(json.loads(ln)), ["bpm", "modality", "night"])


if __name__ == "__main__":
    unittest.main()
