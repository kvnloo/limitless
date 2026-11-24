"""limitless_status and the context packet carry the push-reach words (push_reach) as a ``delivery`` row: value
the card line's words, modality measured, age_h None, evidence_tier. Synthetic state, synthetic Hermes homes
with and without the sender profile, synthetic kevin-push logs, a fixed clock, env passed explicitly."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import context_packet as cp, plugin, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_push_reach_card import (Base, DELIVERED_LAST, FAILING_LAST, NOW, PREFIX, SEND_FAILING,  # noqa: E402
                                  SENDER_MISSING, TODAY, write_log)

FIELDS = {"value", "modality", "age_h", "evidence_tier"}


class Status(Base):
    def status(self):
        return tools.status_with_delivery(StateReader(self.st), NOW, json.loads(self.cfg.read_text()), self.env,
                                          TODAY)

    def call(self):
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch("time.time", return_value=NOW):
            return json.loads(plugin._handler(plugin.TOOLS["limitless_status"][1])({}))

    def test_a_missing_sender_is_the_delivery_value(self):
        write_log(self.log, DELIVERED_LAST)
        d = self.status()["delivery"]
        self.assertEqual(d, {"value": SENDER_MISSING, "modality": "measured", "age_h": None,
                             "evidence_tier": "stale"})

    def test_failed_last_pushes_are_the_delivery_value(self):
        self.sender()
        write_log(self.log, FAILING_LAST)
        self.assertEqual(self.status()["delivery"]["value"], SEND_FAILING)

    def test_no_outage_is_value_none_with_a_reason(self):
        self.sender()
        write_log(self.log, DELIVERED_LAST)
        d = self.status()["delivery"]
        self.assertIsNone(d["value"])
        self.assertEqual((d["modality"], d["age_h"], d["evidence_tier"]), ("measured", None, "none"))
        self.assertNotRegex(d["reason"], r"\d")

    def test_the_inputs_part_is_unchanged(self):
        write_log(self.log, DELIVERED_LAST)
        out = self.status()
        base = tools.status(StateReader(self.st), NOW, {})
        self.assertEqual({k: v for k, v in out.items() if k != "delivery"}, base)

    def test_the_tool_carries_it_through_the_plugin(self):
        write_log(self.log, FAILING_LAST)
        res = self.call()
        self.assertTrue(FIELDS <= set(res))
        self.assertEqual(res["delivery"]["value"], SENDER_MISSING)
        self.assertEqual(res["label"]["label"], "fresh")   # the status label is the one it always was

    def test_no_inputs_still_says_whether_pushes_reach(self):
        (self.st / "inputs.json").unlink()
        write_log(self.log, DELIVERED_LAST)
        res = self.call()
        self.assertIsNone(res["value"])
        self.assertEqual(res["delivery"]["value"], SENDER_MISSING)


class Packet(Base):
    def rows(self):
        p = cp.packet(self.st, NOW, TODAY, self.env)
        return p, {r["key"]: r for r in p["rows"]}

    def test_the_packet_carries_the_same_row(self):
        write_log(self.log, FAILING_LAST)
        p, rows = self.rows()
        self.assertEqual(rows["delivery"], {"key": "delivery", "words": SENDER_MISSING, "modality": "measured",
                                            "evidence_tier": "stale", "age_words": cp.AGE_UNKNOWN})
        self.assertEqual(re.findall(r"\d", cp.text(p)), [])

    def test_no_outage_is_an_unknown_row_never_alarming(self):
        self.sender()
        write_log(self.log, DELIVERED_LAST)
        _, rows = self.rows()
        self.assertNotIn(PREFIX, rows["delivery"]["words"])
        self.assertEqual(rows["delivery"]["evidence_tier"], "none")


if __name__ == "__main__":
    unittest.main()
