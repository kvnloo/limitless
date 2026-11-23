"""The owner-message input: an evidence envelope {value: ISO time, modality: "messages", age_h, evidence_tier}
with a digit-free T1 label, in limitless_state and the pre_llm_call card. Synthetic data only."""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card, labeler, plugin, tools  # noqa: E402
from limitless import envelope as e  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_owner_messages import CONTENT, H, NOW, make_db  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
TODAY = date(2030, 1, 15)
KIND = "owner_message_age_h"


class Modality(unittest.TestCase):
    def test_messages_is_a_modality_and_direct_when_fresh(self):
        self.assertIn("messages", e.MODALITIES)
        self.assertEqual(e.envelope("2030-01-15T10:00:00+00:00", "messages", 2)["evidence_tier"], "direct")
        self.assertEqual(e.envelope("2030-01-14T10:00:00+00:00", "messages", 26)["evidence_tier"], "stale")


class Label(unittest.TestCase):
    def test_three_digit_free_words(self):
        self.assertEqual(labeler.ALLOWED[KIND], ("wrote recently", "quiet for a while", "no data"))
        self.assertEqual(labeler.rule_label(KIND, 0.0), "wrote recently")
        self.assertEqual(labeler.rule_label(KIND, labeler.OWNER_RECENT_H), "wrote recently")
        self.assertEqual(labeler.rule_label(KIND, labeler.OWNER_RECENT_H + 0.1), "quiet for a while")
        self.assertEqual(labeler.rule_label(KIND, 300.0), "quiet for a while")
        self.assertEqual(labeler.rule_label(KIND, None), "no data")
        for bad in (-1, "2", True, float("nan")):
            self.assertEqual(labeler.rule_label(KIND, bad), labeler.UNKNOWN, bad)
        for w in labeler.ALLOWED[KIND]:
            self.assertFalse(any(c.isdigit() for c in w))
        self.assertEqual(labeler.label(KIND, 1.0, "messages")["modality"], "messages")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "st"
        shutil.copytree(FIX, self.st)
        self.laptop = make_db(self.dir / "laptop.db", [("s-cli", "user", CONTENT, NOW - 26 * H)])
        self.server = make_db(self.dir / "server.db", [("s-tg", "user", CONTENT, NOW - 0.5 * H)])
        self.env = {"LIMITLESS_CONFIG": str(self.dir / "no-config.json"), "LIMITLESS_STATE": str(self.st)}

    def tearDown(self):
        self.tmp.cleanup()

    def with_dbs(self, *dbs):
        return dict(self.env, LIMITLESS_OWNER_DBS=os.pathsep.join(str(d) for d in dbs))


class Tool(Base):
    def test_envelope_from_every_db(self):
        env = tools.owner_message(StateReader(self.st), NOW, self.with_dbs(self.laptop, self.server))
        self.assertEqual(env["value"], "2030-01-15T11:30:00+00:00")
        self.assertEqual((env["modality"], env["age_h"], env["evidence_tier"]), ("messages", 0.5, "direct"))
        self.assertEqual(env["label"], {"label": "wrote recently", "tier": "T1", "modality": "messages"})
        self.assertEqual(env["sources"], {"read": 2, "failed": 0})
        self.assertNotIn("synthetic", json.dumps(env))

    def test_one_machine_alone_is_quiet_and_stale(self):
        env = tools.owner_message(StateReader(self.st), NOW, self.with_dbs(self.laptop))
        self.assertEqual((env["age_h"], env["evidence_tier"]), (26.0, "stale"))
        self.assertEqual(env["label"]["label"], "quiet for a while")

    def test_no_paths_is_missing_not_zero(self):
        env = tools.owner_message(StateReader(self.st), NOW, self.env)
        self.assertIsNone(env["value"])
        self.assertIsNone(env["age_h"])
        self.assertEqual(env["evidence_tier"], "none")
        self.assertIn("LIMITLESS_OWNER_DBS", env["reason"])

    def test_every_db_failing_or_empty_is_no_data_with_a_reason(self):
        quiet = make_db(self.dir / "quiet.db", [("s-cli", "assistant", CONTENT, NOW - H)])
        for dbs, why in (((self.dir / "gone.db",), "could not be read"), ((quiet,), "no message from the person")):
            env = tools.owner_message(StateReader(self.st), NOW, self.with_dbs(*dbs))
            self.assertIsNone(env["value"])
            self.assertIn(why, env["reason"])
            self.assertEqual(env["label"]["label"], "no data")
            self.assertNotIn(str(self.dir), json.dumps(env))  # reasons never echo a path


class Card(Base):
    def build(self, env, **kw):
        return card.build(StateReader(self.st), NOW, TODAY, env=env, **kw)

    def test_card_line_carries_the_label_only(self):
        c = self.build(self.with_dbs(self.laptop, self.server))
        self.assertIn("messages: wrote recently", c["text"])
        self.assertEqual(c["items"]["owner_message"]["value"], "2030-01-15T11:30:00+00:00")
        self.assertLessEqual(len(c["lines"]), card.MAX_LINES)
        self.assertIn("asks waiting on you", c["text"])  # the new segment does not push a line off

    def test_no_dbs_configured_adds_nothing_to_the_card(self):
        c = self.build(self.env)
        self.assertNotIn("messages:", c["text"])
        self.assertIsNone(c["items"]["owner_message"]["value"])

    def test_configured_but_unreadable_says_no_data(self):
        self.assertIn("messages: no data", self.build(self.with_dbs(self.dir / "gone.db"))["text"])

    def test_state_tool_keeps_proxy_as_weakest(self):
        env = card.state(StateReader(self.st), NOW, TODAY, env=self.with_dbs(self.server))
        self.assertEqual(env["modality"], "proxy")
        self.assertEqual(env["value"]["items"]["owner_message"]["modality"], "messages")

    def test_cache_rebuilds_when_the_label_changes(self):
        c = card.CardCache()
        r = StateReader(self.st)
        a = c.get(r, NOW, TODAY, env=self.with_dbs(self.server))
        b = c.get(r, NOW + 60, TODAY, env=self.with_dbs(self.server))
        self.assertEqual((a, c.builds), (b, 1))
        later = c.get(r, NOW + 5 * H, TODAY, env=self.with_dbs(self.server))
        self.assertEqual(c.builds, 2)
        self.assertIn("messages: quiet for a while", later)

    def test_plugin_state_handler_returns_the_item(self):
        with mock.patch.dict(os.environ, self.with_dbs(self.server), clear=False), \
                mock.patch.object(plugin.time, "time", return_value=NOW):
            out = json.loads(plugin._handler(plugin._state)({}))
        self.assertEqual(out["value"]["items"]["owner_message"]["label"]["label"], "wrote recently")


if __name__ == "__main__":
    unittest.main()
