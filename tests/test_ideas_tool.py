"""limitless_ideas: the idea ledger's week in words, read-only; idea text only under the raw opt-in."""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import idea_ledger, plugin, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NOW = 1894708800.0                       # synthetic clock
H = 3600.0


def iso(t):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def row(text, at, status="new"):
    return {"kind": "idea", "id": idea_ledger.idea_id(text), "at": iso(at), "text": text, "source": "hermes",
            "status": status}


class Week(unittest.TestCase):
    def test_counts_this_weeks_ideas_and_how_many_the_person_triaged(self):
        rows = [row("old synthetic idea", NOW - 9 * 24 * H), row("synthetic a", NOW - 30 * H),
                row("synthetic b", NOW - 5 * H, "parked"), row("synthetic c", NOW - 2 * H)]
        w = idea_ledger.week(rows, NOW)
        self.assertEqual((w["recorded"], w["triaged"]), (3, 1))
        self.assertEqual(w["newest_at"], NOW - 2 * H)
        self.assertEqual([r["text"] for r in w["ideas"]], ["synthetic a", "synthetic b", "synthetic c"])

    def test_the_latest_row_for_an_id_carries_its_status(self):
        a = row("synthetic a", NOW - 30 * H)
        later = {"kind": "idea", "id": a["id"], "at": a["at"], "status": "done"}   # the person's own later row
        w = idea_ledger.week([a, later], NOW)
        self.assertEqual((w["recorded"], w["triaged"]), (1, 1))

    def test_rows_after_now_are_not_this_week(self):
        self.assertEqual(idea_ledger.week([row("future", NOW + 2 * H)], NOW)["recorded"], 0)

    def test_label_words(self):
        cases = {(0, 0): "no new ideas this week", (1, 0): "one new idea this week, not triaged yet",
                 (1, 1): "one new idea this week, triaged", (2, 0): "two new ideas this week, none triaged",
                 (4, 0): "a few new ideas this week, none triaged", (4, 1): "a few new ideas this week, some triaged",
                 (5, 5): "a few new ideas this week, all triaged", (8, 2): "several new ideas this week, some triaged",
                 (30, 0): "many new ideas this week, none triaged"}
        for (n, t), want in cases.items():
            got = idea_ledger.label({"recorded": n, "triaged": t})
            self.assertEqual(got, want)
            self.assertEqual(re.findall(r"\d", got), [])


class Tool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.reader = StateReader(self.home)
        self.ledger = self.home / "ideas.jsonl"
        rows = [row("synthetic idea one", NOW - 30 * H), row("synthetic idea two", NOW - 3 * H),
                row("synthetic idea three", NOW - 2 * H)]
        self.ledger.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.env = {"LIMITLESS_CONFIG": str(self.home / "none.json"), "LIMITLESS_IDEA_LEDGER": str(self.ledger)}

    def test_envelope_label_in_words_no_text(self):
        before = self.ledger.read_bytes()
        res = tools.ideas(self.reader, NOW, env=self.env, home=self.home)
        self.assertEqual(res["value"], {"label": "a few new ideas this week, none triaged"})
        self.assertEqual((res["modality"], res["age_h"], res["evidence_tier"]), ("self_report", 2.0, "direct"))
        self.assertEqual(res["label"], {"label": "a few new ideas this week, none triaged", "tier": "T1",
                                        "modality": "self_report"})
        self.assertNotIn("synthetic idea", json.dumps(res))
        self.assertEqual(self.ledger.read_bytes(), before)            # read-only

    def test_raw_opt_in_adds_the_counts_and_text(self):
        res = tools.ideas(self.reader, NOW, raw=True, env=self.env, home=self.home)
        self.assertEqual((res["value"]["recorded"], res["value"]["triaged"]), (3, 0))
        self.assertEqual([r["text"] for r in res["value"]["ideas"]],
                         ["synthetic idea one", "synthetic idea two", "synthetic idea three"])

    def test_old_newest_row_is_stale(self):
        self.ledger.write_text(json.dumps(row("synthetic old", NOW - 9 * 24 * H)) + "\n")
        res = tools.ideas(self.reader, NOW, env=self.env, home=self.home)
        self.assertEqual((res["value"]["label"], res["evidence_tier"]), ("no new ideas this week", "stale"))

    def test_unset_ledger_is_missing_with_the_reason(self):
        res = tools.ideas(self.reader, NOW, env={"LIMITLESS_CONFIG": str(self.home / "none.json")}, home=self.home)
        self.assertEqual((res["value"], res["evidence_tier"], res["reason"]), (None, "none", "no idea ledger set"))

    def test_empty_ledger_says_so(self):
        self.ledger.write_text("")
        res = tools.ideas(self.reader, NOW, env=self.env, home=self.home)
        self.assertEqual((res["value"], res["age_h"]), ({"label": "no new ideas this week"}, None))

    def test_through_the_plugin_handler_text_needs_the_opt_in(self):
        env = dict(self.env, LIMITLESS_STATE=str(self.home))
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("time.time", return_value=NOW):
            res = json.loads(plugin._handler(plugin.TOOLS["limitless_ideas"][1], "limitless_ideas")({}))
            self.assertNotIn("synthetic idea", json.dumps(res))
            self.assertEqual(res["label"]["label"], "a few new ideas this week, none triaged")
        with mock.patch.dict(os.environ, dict(env, LIMITLESS_RAW_IN_PROMPT="1"), clear=True), \
                mock.patch("time.time", return_value=NOW):
            res = json.loads(plugin._handler(plugin.TOOLS["limitless_ideas"][1], "limitless_ideas")({}))
            self.assertIn("synthetic idea two", json.dumps(res))

    def test_manifest_lists_the_tool(self):
        self.assertIn("  - limitless_ideas\n", (ROOT / "plugin.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
