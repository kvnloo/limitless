"""The sender confirmation's schedule card (schedule_cards.sender_confirm_card, limitless_schedule) and its doc:
docs/sender-confirm.md shows the real output of scripts/sender_confirm_example.py, names its rules, and the README
and sibling docs point at it. Synthetic only; nothing is sent.""" 
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from limitless import schedule_cards, send_gate, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

DOC = ROOT / "docs" / "sender-confirm.md"
NOW = 1894708800.0
CLOCK = re.compile(r"\b\d{1,2}:\d{2}\b|\bcron\b|\*/\d", re.I)


class Card(unittest.TestCase):
    def test_the_card_is_an_event_card_sent_by_the_plugin(self):
        c = schedule_cards.sender_confirm_card()
        self.assertEqual((c["id"], c["kind"], c["trigger"], c["ends"]),
                         ("sender_confirm", "schedule", "sender_changed", "sender_changed"))
        self.assertEqual((c["sender"], c["budget"], c["per_window"]), (schedule_cards.PLUGIN, send_gate.DAILY_CAP, 1))
        self.assertEqual(c["once_key"], "sender_confirm:<sender reply time>")
        self.assertEqual(c["name"], "Pushes")
        self.assertIn("right after your reply changes the sender for your pushes", c["description"])
        self.assertIsNone(CLOCK.search(json.dumps(c)))
        self.assertIsNone(re.search(r"\d", c["description"]))

    def test_cards_add_it_only_when_the_job_is_on_before_the_recap(self):
        self.assertNotIn("sender_confirm", [c["id"] for c in schedule_cards.cards()])
        ids = [c["id"] for c in schedule_cards.cards(sender=True, confirm=True, recap=True)]
        self.assertEqual(ids[-3:], ["sender_ingest", "sender_confirm", "outage_recap"])

    def test_limitless_schedule_carries_it_when_config_is_not_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.json"
            env = {"HOME": tmp, "LIMITLESS_CONFIG": str(cfg)}
            st = Path(tmp) / "state"
            st.mkdir()
            cfg.write_text(json.dumps({}))
            ids = [c["id"] for c in tools.schedule(StateReader(st), NOW, env)["value"]["cards"]]
            self.assertNotIn("sender_confirm", ids)
            cfg.write_text(json.dumps({"sender_confirm": "dry_run"}))
            out = tools.schedule(StateReader(st), NOW, env)
            self.assertEqual(out["value"]["cards"][-1]["id"], "sender_confirm")
            self.assertIn("lines", out)


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "sender_confirm_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        for said in ("This is the new route for your phone pushes. If you see this, it works.",
                     "Sender confirm: hold: your reply changed the sender for your phone pushes; the new sender did "
                     "not reach you: the send failed",
                     "job sender confirm: missing: sender confirm: the new sender did not reach you",
                     "Sleep mode holds it", "job sender confirm: live: sender confirm: waits",
                     "job sender confirm: live: sender confirm: the new sender reached you",
                     "Sender confirm: drop: this sender change was already confirmed",
                     "Outage recap: hold: pushes came back after an outage; waits for the next pass"):
            self.assertIn(said, r.stdout)
        self.assertNotIn("backup", r.stdout.split("# pass")[1] if "# pass" in r.stdout else r.stdout)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_doc_names_its_rules(self):
        text = DOC.read_text()
        for word in ("sender_changed", "push-sender.json", "sender-confirm.json", "0600", "--once",
                     "sender_confirm:<sender reply time>", "`off`", "`dry_run`", "`write`", "never a clock",
                     "no digit", "Sleep mode", "KEVIN_PUSH_PROFILE", "push_log", "limitless-doctor",
                     "job sender confirm", "outage recap", "next pass", "duplicate"):
            self.assertIn(word, text)

    def test_the_readme_and_sibling_docs_point_at_it(self):
        readme = (ROOT / "README.md").read_text()
        for word in ("limitless/sender_confirm_job.py", "docs/sender-confirm.md", "sender_confirm"):
            self.assertIn(word, readme)
        for doc in ("doctor.md", "schedule-cards.md", "push-sender-reply.md", "outage-recap.md"):
            self.assertIn("sender-confirm.md", (ROOT / "docs" / doc).read_text(), doc)


if __name__ == "__main__":
    unittest.main()
