"""limitless_card_view kind skill_tree: the skill tree as one self-contained HTML card through ui_card, one
digit-free row per layer, written only when a card dir is set. Synthetic only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import stat
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card_view, habit_catalogue, plugin, skill_tree, stop_rule, ui_card  # noqa: E402

NOW = 1894708800.0
TODAY = date.fromtimestamp(NOW)
CAT = habit_catalogue.CATALOGUE


def visible(html):
    return re.sub(r"<[^>]*>", "", re.search(r"(?s)<body>(.*)</body>", html).group(1))


class Card(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cards = self.root / "cards"
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def view(self, **env):
        return card_view.view(self.st, NOW, TODAY, "skill_tree", env=dict(self.env, **env), home=self.root)

    def decide(self, habit, decision, week_of):
        stop_rule.record_loop(self.st, {"habit": habit, "week_of": week_of, "checkins": {week_of: "Done"}},
                              decision, f"{week_of}T09:00:00+00:00", now=NOW)

    def test_kind_is_listed(self):
        self.assertIn("skill_tree", ui_card.KINDS)
        self.assertIn("skill_tree", card_view.LABEL)

    def test_no_card_dir_renders_only_and_writes_nothing(self):
        r = self.view()
        self.assertIsNone(r["value"]["path"])
        self.assertEqual(r["note"], ui_card.NO_DIR)
        self.assertFalse(self.cards.exists())
        self.assertEqual(r["value"]["rows"], len(skill_tree.LAYERS))

    def test_card_has_one_row_per_layer_the_tree_lines(self):
        self.decide(CAT[0]["name"], "Keep", "2030-01-01")
        self.decide(CAT[1]["name"], "Drop", "2030-01-08")
        (self.st / "habit.json").write_text(json.dumps({"habit": CAT[2]["name"], "week_of": TODAY.isoformat(),
                                                        "checkins": {}}))
        r = self.view(LIMITLESS_CARD_DIR=str(self.cards))
        p = Path(r["value"]["path"])
        self.assertEqual(p.parent, self.cards)
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        html = p.read_text(encoding="utf-8")
        text = visible(html)
        t = skill_tree.tree(CAT, stop_rule.loop_rows(self.st), current=CAT[2]["name"])
        for ln in skill_tree.lines(t):
            self.assertIn(ln, text)
        self.assertIn(ui_card.TITLES["skill_tree"], html)
        self.assertEqual((r["value"]["rows"], r["value"]["dropped"]), (len(skill_tree.LAYERS), 0))
        self.assertEqual(r["modality"], "derived")
        self.assertIsNone(r["age_h"])
        self.assertEqual(r["evidence_tier"], "stale")
        self.assertEqual(r["label"], {"label": "a skill tree card with four rows", "tier": "T1",
                                      "modality": "derived"})

    def test_self_contained_no_script_and_digit_free(self):
        r = self.view(LIMITLESS_CARD_DIR=str(self.cards))
        html = Path(r["value"]["path"]).read_text(encoding="utf-8")
        for bad in ("<script", "<link", "<img", "src=", "href=", "@import", "url("):
            self.assertNotIn(bad, html.lower())
        self.assertNotRegex(visible(html), r"\d")
        for w in ("score", "level", "percent", "xp", "streak"):
            self.assertNotIn(w, visible(html).lower())

    def test_a_later_layer_row_is_a_held_chip(self):
        r = ui_card.render(ui_card.TITLES["skill_tree"], skill_tree.lines(skill_tree.tree(CAT, {})), "skill_tree")
        chips = [c for _, c in r["chips"]]
        self.assertEqual(chips[0], ui_card.KNOWN)
        self.assertEqual(chips[1:], [ui_card.HELD] * (len(skill_tree.LAYERS) - 1))

    def test_the_same_tree_is_the_same_file(self):
        a = self.view(LIMITLESS_CARD_DIR=str(self.cards))["value"]["path"]
        b = self.view(LIMITLESS_CARD_DIR=str(self.cards))["value"]["path"]
        self.assertEqual(a, b)
        self.assertEqual(len(list(self.cards.iterdir())), 1)

    def test_the_ledger_is_never_written(self):
        self.decide(CAT[0]["name"], "Keep", "2030-01-01")
        before = (self.st / "predictions.jsonl").read_bytes()
        self.view(LIMITLESS_CARD_DIR=str(self.cards))
        self.assertEqual((self.st / "predictions.jsonl").read_bytes(), before)
        self.assertEqual(sorted(f.name for f in self.st.iterdir()), ["predictions.jsonl"])

    def test_an_unknown_kind_is_still_refused(self):
        r = card_view.view(self.st, NOW, TODAY, "bogus", env=self.env, home=self.root)
        self.assertIsNone(r["value"])
        self.assertIn("skill_tree", r["reason"])


class Plugin(unittest.TestCase):
    def test_schema_offers_the_kind(self):
        schema = plugin.TOOLS["limitless_card_view"][0]
        self.assertIn("skill_tree", schema["parameters"]["properties"]["kind"]["enum"])
        self.assertIn("skill tree", schema["description"])

    def test_handler_kind_skill_tree(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        st = Path(tmp.name) / "state"
        st.mkdir()
        env = {"LIMITLESS_STATE": str(st), "LIMITLESS_CONFIG": str(Path(tmp.name) / "none.json")}
        with mock.patch.dict(os.environ, env, clear=False), mock.patch("time.time", return_value=NOW):
            os.environ.pop("LIMITLESS_CARD_DIR", None)
            out = json.loads(plugin._handler(plugin.TOOLS["limitless_card_view"][1], "limitless_card_view")(
                {"kind": "skill_tree"}))
        self.assertIsNone(out["value"]["path"])
        self.assertEqual(out["label"]["label"], "a skill tree card with four rows")


if __name__ == "__main__":
    unittest.main()
