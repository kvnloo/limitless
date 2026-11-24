"""skills/learn/SKILL.md: the plugin's learning skill (limitless:learn) stays short, names only real tools, runs a
learning turn as struggle-first guess, explain-back, a notebook of unknowns and trough-only Anki review, and never
holds a clock time, a dosing word or a score/grade offered as a feature."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skill_checks import (clock_hits, dosing_hits, frontmatter, named_tools, score_as_feature,  # noqa: E402
                          sentences, table_tools)
from test_plugin import manifest_list  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "learn" / "SKILL.md"
MAX_LINES = 100
# the tools a learning turn runs over; each must be in the question -> tool table
LEARNING_TOOLS = {"limitless_window", "limitless_capture", "limitless_explain_back", "limitless_anki",
                  "limitless_ideas", "limitless_palace"}


def text():
    return SKILL.read_text()


def flat(src):
    return " ".join(src.lower().split())   # markdown wraps lines anywhere


class Format(unittest.TestCase):
    def test_frontmatter_parses_and_the_name_matches_the_dir(self):
        fm, body = frontmatter(text())
        self.assertEqual(fm["name"], SKILL.parent.name)
        self.assertEqual(fm["name"], "learn")
        self.assertTrue(body.strip())

    def test_the_name_is_a_valid_bare_skill_name(self):
        name = frontmatter(text())[0]["name"]
        self.assertRegex(name, r"^[a-zA-Z0-9_-]+$")
        self.assertNotIn(":", name)

    def test_the_description_is_use_when_trigger_then_behavior(self):
        desc = frontmatter(text())[0]["description"]
        self.assertRegex(desc, r"^Use when [^.]+\. [A-Z][^.]*\.$")

    def test_short(self):
        self.assertLessEqual(len(text().split("\n")), MAX_LINES)


class Tools(unittest.TestCase):
    def test_every_tool_named_is_in_plugin_yaml(self):
        named = named_tools(text())
        self.assertTrue(named)
        self.assertEqual(sorted(named - set(manifest_list("provides_tools"))), [])

    def test_the_table_names_every_learning_tool(self):
        self.assertEqual(sorted(LEARNING_TOOLS - table_tools(frontmatter(text())[1])), [])

    def test_anki_review_is_offered_only_in_a_trough(self):
        said = [s.lower() for s in sentences(frontmatter(text())[1])
                if "limitless_anki" in s and not s.startswith("|")]
        self.assertTrue(said)
        for s in said:
            self.assertIn("trough", s, s)
        low = flat(frontmatter(text())[1])
        self.assertIn("only when `limitless_window` says trough", low)

    def test_memory_palace_walk_is_offered_only_in_a_trough(self):
        body = frontmatter(text())[1]
        said = [s.lower() for s in sentences(body) if "limitless_palace" in s]
        self.assertTrue(said)
        for s in said:
            self.assertIn("trough", s, s)
        low = flat(body)
        self.assertIn("only when `limitless_palace` says fits now", low)
        self.assertIn("one learning offer per trough", low)


class Never(unittest.TestCase):
    def test_no_clock_time(self):
        self.assertEqual(clock_hits(text()), [])

    def test_no_dosing_words(self):
        self.assertEqual(dosing_hits(text()), [])

    def test_no_score_or_grade_offered_as_a_feature(self):
        self.assertEqual(score_as_feature(text()), [])
        self.assertNotRegex(text().lower(), r"\byour (score|level|xp|grade|streak)\b")

    def test_says_never_graded_and_never_scored(self):
        low = flat(text())
        for phrase in ("never graded", "never scored", "no score, grade, level or streak", "never a clock time",
                       "never advise on drugs"):
            self.assertIn(phrase, low)


class LearningTurn(unittest.TestCase):
    def test_the_steps_in_order(self):
        low = flat(frontmatter(text())[1])
        idx = [low.find(w) for w in ("struggle-first guess", "explain-back", "notebook of unknowns",
                                     "spaced review")]
        self.assertNotIn(-1, idx, idx)
        self.assertEqual(idx, sorted(idx))

    def test_the_guess_comes_before_any_explanation(self):
        self.assertIn("before any explanation", flat(text()))

    def test_explain_back_is_own_words_and_saved_as_kind_explain_back(self):
        low = flat(text())
        for phrase in ("own words", "voice", "kind: explain_back"):
            self.assertIn(phrase, low)

    def test_unknowns_are_captured_and_reviewed_in_the_week_review(self):
        low = flat(text())
        self.assertIn("open question", low)
        self.assertIn("week review", low)

    def test_one_step_a_turn_and_a_decline_is_never_a_miss(self):
        low = flat(text())
        for phrase in ("at most one learning step", "decline", "never logged as a miss"):
            self.assertIn(phrase, low)

    def test_t2_quotes_digit_free_labels(self):
        low = flat(text())
        self.assertIn("t2", low)
        self.assertIn("digit-free label", low)

    def test_suggest_only(self):
        low = flat(text())
        for phrase in ("no new job", "no autonomous action"):
            self.assertIn(phrase, low)


if __name__ == "__main__":
    unittest.main()
