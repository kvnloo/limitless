"""The outage recap's schedule card (schedule_cards.outage_recap_card, limitless_schedule) and its doctor row
(doctor.outage_recap_row: off / waiting / told / nothing to recap). Synthetic kevin-push logs in a temp state dir,
a fixed clock, env passed explicitly. Nothing is sent."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import doctor, jobs, schedule_cards, send_gate, tools  # noqa: E402
from limitless import outage_recap_job as job  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 1894708800.0   # 2030-01-15T12:00:00Z
H = 3600
RC1 = "log (telegram rc=1)"
CLOCK = re.compile(r"\b\d{1,2}:\d{2}\b|\bcron\b|\*/\d", re.I)


def row(at, title, how):
    return {"at": int(at), "tag": "limitless", "cls": "decision", "title": title, "body": "x", "how": how}


OPEN = [row(NOW - 5 * H, "Wake-up brief", RC1), row(NOW - 4 * H, "Back from nap", RC1)]
CLOSED = OPEN + [row(NOW - 600, "Habit check-in", "telegram")]


class Card(unittest.TestCase):
    def test_the_card_is_an_event_card_sent_by_the_plugin(self):
        c = schedule_cards.outage_recap_card()
        self.assertEqual((c["id"], c["kind"], c["trigger"], c["ends"]), ("outage_recap", "schedule", "push_back",
                                                                         "push_back"))
        self.assertEqual((c["sender"], c["budget"], c["per_window"]), (schedule_cards.PLUGIN, send_gate.DAILY_CAP, 1))
        self.assertEqual(c["once_key"], "outage_recap:<first failed push time>")
        self.assertEqual(c["name"], "Pushes are back")
        self.assertIn("when a push reaches you again after pushes stopped getting through", c["description"])
        self.assertIn("OK or More in one tap", c["words"]["answers"])
        self.assertIsNone(CLOCK.search(json.dumps(c)))
        self.assertIsNone(re.search(r"\d", c["description"]))

    def test_cards_add_it_only_when_the_job_is_on(self):
        ids = [c["id"] for c in schedule_cards.cards()]
        self.assertNotIn("outage_recap", ids)
        self.assertEqual(schedule_cards.cards(recap=True)[-1]["id"], "outage_recap")

    def test_limitless_schedule_carries_it_when_config_is_not_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.json"
            env = {"HOME": tmp, "LIMITLESS_CONFIG": str(cfg)}
            st = Path(tmp) / "state"
            st.mkdir()
            cfg.write_text(json.dumps({}))
            ids = [c["id"] for c in tools.schedule(StateReader(st), NOW, env)["value"]["cards"]]
            self.assertNotIn("outage_recap", ids)
            cfg.write_text(json.dumps({"outage_recap": "dry_run"}))
            out = tools.schedule(StateReader(st), NOW, env)
            self.assertEqual(out["value"]["cards"][-1]["id"], "outage_recap")
            self.assertIn("lines", out)


class DoctorRow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)
        self.reader = StateReader(self.st)

    def tearDown(self):
        self.tmp.cleanup()

    def log(self, rows):
        (self.st / "push-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def row(self, mode="write", log="push-log.jsonl", now=NOW):
        cfg = {"outage_recap": mode} if mode else {}
        if log:
            cfg["push_log"] = log
        return doctor.outage_recap_row(self.reader, cfg, now)

    def test_off(self):
        r = self.row(mode=None)
        self.assertEqual((r["name"], r["kind"], r["status"]), (doctor.OUTAGE_RECAP_ROW, "job", doctor.OFF))
        self.assertEqual(r["reason"], "outage recap: off (config outage_recap)")

    def test_no_push_log(self):
        r = self.row(log=None)
        self.assertEqual(r["status"], doctor.MISSING)
        self.assertIn("no push log set", r["reason"])

    def test_waiting_while_open_and_after_it_closed(self):
        self.log(OPEN)
        r = self.row()
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertEqual(r["reason"], "outage recap: waiting: pushes are still failing; write mode")
        self.log(CLOSED)
        self.assertEqual(self.row()["reason"], "outage recap: waiting: pushes came back after an outage; the next "
                                               "pass sends the recap; write mode")
        self.assertIn("dry run mode", self.row(mode="dry_run")["reason"])

    def test_told(self):
        self.log(CLOSED)
        (self.st / job.MARK).write_text(json.dumps({"key": f"outage_recap:{int(NOW - 5 * H)}", "outcome": job.TOLD,
                                                    "at": NOW - 300}))
        r = self.row()
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertTrue(r["reason"].startswith("outage recap: told: the last outage was recapped "), r["reason"])
        self.assertIsNone(re.search(r"\d", doctor.words(r["reason"])))

    def test_nothing_to_recap(self):
        self.log([row(NOW - H, "Wake-up brief", "telegram")])
        self.assertEqual(self.row()["reason"], "outage recap: nothing to recap; write mode")
        self.log(CLOSED)
        self.assertEqual(self.row(now=NOW + jobs.OUTAGE_RECAP_STALE_S + H)["reason"],
                         "outage recap: nothing to recap; write mode")

    def test_report_has_the_row_once(self):
        with mock.patch.object(doctor, "outage_recap_row", wraps=doctor.outage_recap_row) as spy:
            rows = doctor.report({"outage_recap": "off", "state": str(self.st)}, NOW)
        self.assertEqual([r["name"] for r in rows].count(doctor.OUTAGE_RECAP_ROW), 1)
        self.assertEqual(spy.call_count, 1)


if __name__ == "__main__":
    unittest.main()
