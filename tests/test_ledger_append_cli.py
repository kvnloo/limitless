"""bin/limitless-ledger-append end to end, and its one schedule card. Synthetic fixtures only."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, plugin, schedule_cards, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-ledger-append"
CAPS = [{"at": "2030-01-07T21:00:00+00:00", "text": "Synthetic idea about a reading lamp", "source": "hermes"},
        {"at": "2030-01-07T22:30:00+00:00", "text": "Another synthetic idea", "source": "bedtime"}]
CLOCK = re.compile(r"\d|:\d|\b(am|pm)\b|\*|@(daily|hourly|weekly|midnight)|\bevery\b|\bcron\b|o'clock", re.I)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.state = self.home / "state"
        self.state.mkdir()
        (self.state / "captures.jsonl").write_text("".join(json.dumps(c) + "\n" for c in CAPS))
        self.ledger = self.state / "ideas.jsonl"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
        self.env.update(HOME=str(self.home), LIMITLESS_STATE=str(self.state))

    def run_cli(self, *args, **env):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=dict(self.env, **env), cwd=self.home,
                              capture_output=True, text=True, timeout=30)

    def test_unset_ledger_does_nothing_and_says_why(self):
        r = self.run_cli("--write")
        self.assertEqual((r.returncode, r.stdout), (0, "no idea ledger set\n"), r.stderr)
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), ["captures.jsonl"])

    def test_dry_run_by_default(self):
        r = self.run_cli(LIMITLESS_IDEA_LEDGER=str(self.ledger))
        self.assertEqual((r.returncode, r.stdout), (0, "would append two ideas\n"), r.stderr)
        self.assertFalse(self.ledger.exists())

    def test_write_then_rerun_appends_nothing(self):
        r = self.run_cli("--write", LIMITLESS_IDEA_LEDGER=str(self.ledger))
        self.assertEqual((r.returncode, r.stdout), (0, "appended two ideas\n"), r.stderr)
        self.assertEqual(len(self.ledger.read_text().splitlines()), 2)
        r = self.run_cli("--write", LIMITLESS_IDEA_LEDGER=str(self.ledger))
        self.assertEqual((r.returncode, r.stdout), (0, "no new ideas\n"), r.stderr)
        self.assertEqual(len(self.ledger.read_text().splitlines()), 2)

    def test_config_key(self):
        cfg = self.home / ".config/limitless/config.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"idea_ledger": "ideas.jsonl"}))
        r = self.run_cli("--write")
        self.assertEqual((r.returncode, r.stdout), (0, "appended two ideas\n"), r.stderr)
        self.assertTrue(self.ledger.exists())

    def test_idea_text_only_with_show(self):
        r = self.run_cli(LIMITLESS_IDEA_LEDGER=str(self.ledger))
        for c in CAPS:
            self.assertNotIn(c["text"], r.stdout + r.stderr)
        r = self.run_cli("--show", LIMITLESS_IDEA_LEDGER=str(self.ledger))
        self.assertEqual(r.stdout.splitlines(), ["would append two ideas"] + [f"- {c['text']}" for c in CAPS])

    def test_misconfigured_ledger_exits_one(self):
        r = self.run_cli("--write", LIMITLESS_IDEA_LEDGER=str(self.home / "missing" / "ideas.jsonl"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "not appended: the idea ledger's folder does not exist\n")
        r = self.run_cli("--write", LIMITLESS_IDEA_LEDGER=str(self.state / "captures.jsonl"))
        self.assertEqual((r.returncode, r.stdout), (1, "not appended: the idea ledger cannot be the captures file\n"))

    def test_output_is_digit_free(self):
        for args in ((), ("--write",), ("--write",)):
            r = self.run_cli(*args, LIMITLESS_IDEA_LEDGER=str(self.ledger))
            self.assertFalse(any(ch.isdigit() for ch in r.stdout), r.stdout)

    def test_bad_argument(self):
        r = self.run_cli("--push")
        self.assertEqual(r.returncode, 2)


class Card(unittest.TestCase):
    def test_one_card_on_the_wind_down_event_no_clock(self):
        c = schedule_cards.ledger_card()
        self.assertEqual(set(c), set(schedule_cards.card_for(jobs.MIQ)))
        self.assertEqual((c["id"], c["kind"], c["trigger"], c["ends"], c["window"]),
                         ("idea_ledger", "schedule", "wind_down", "sleep_mode_on", "wind_down"))
        self.assertEqual((c["sender"], c["budget"], c["per_window"]), ("local", 0, 1))
        self.assertIn(c["trigger"], jobs.EVENTS)
        for k in ("trigger", "ends", "once_key", "description"):
            self.assertNotRegex(c[k], CLOCK, k)
        for k, v in c["words"].items():
            self.assertNotRegex(v, CLOCK, k)
        self.assertIn("nothing is sent", c["description"])
        self.assertEqual(c["words"]["runs"], "limitless-ledger-append --write")
        self.assertRegex(c["description"], r"^Schedule \"[^\"\n]+\" \([^\n]+\): [^\n]+$")

    def test_offered_only_when_a_ledger_is_set(self):
        self.assertEqual([c["id"] for c in schedule_cards.cards()], list(jobs.SPECS))
        self.assertEqual([c["id"] for c in schedule_cards.cards(ledger=True)], list(jobs.SPECS) + ["idea_ledger"])
        self.assertNotIn("idea_ledger", jobs.SPECS)          # not a push job: limitless-jobs never runs it

    def test_schedule_tool_and_plugin_offer_it_when_set(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            env = {"LIMITLESS_CONFIG": str(home / "none.json")}
            reader = StateReader(home)
            ids = [c["id"] for c in tools.schedule(reader, 0.0, env=env, home=home)["value"]["cards"]]
            self.assertNotIn("idea_ledger", ids)
            env["LIMITLESS_IDEA_LEDGER"] = str(home / "ideas.jsonl")
            res = tools.schedule(reader, 0.0, env=env, home=home)
            self.assertEqual(res["value"]["cards"][-1]["id"], "idea_ledger")
            self.assertEqual(res["label"]["label"], "seven schedule cards, each on an event, none on a clock")

            got = []

            class Ctx:
                def register_schedule_card(self, card):
                    got.append(card["id"])

            with mock.patch.dict(os.environ, env):
                plugin._register_cards(Ctx())
            self.assertEqual(got[-1], "idea_ledger")


if __name__ == "__main__":
    unittest.main()
