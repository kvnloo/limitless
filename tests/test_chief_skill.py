"""skills/chief/SKILL.md: the plugin's chief-of-staff skill (limitless:chief) stays short, names only real tools, turns
every needs-the-person ask into one row of the asks queue (the fields limitless/asks.py reads) with a one-tap reply,
lets limitless_window and the asks plan decide when it reaches him, keeps one status board in words, and acts only on
his yes. No clock time, no dosing word, no digit outside a fenced example."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skill_checks import (SKILL_MAX_LINES, clock_hits, digits_outside_fences, dosing_hits, fenced,  # noqa: E402
                          frontmatter, named_tools, score_as_feature, table_tools)
from test_plugin import manifest_list  # noqa: E402

from limitless import asks, decision_window, one_tap  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "chief" / "SKILL.md"
# the tools a chief turn reads; each must be in the question -> tool table
CHIEF_TOOLS = {"limitless_window", "limitless_blocks", "limitless_quiet", "limitless_flow_ledger",
               "limitless_overnight"}


def text():
    return SKILL.read_text()


def body():
    return frontmatter(text())[1]


def flat(src):
    return " ".join(src.lower().split())   # markdown wraps lines anywhere


def example():
    """The one fenced JSON example: the ask row the skill tells an agent to append."""
    blocks = [b for b in fenced(text()) if b.lstrip().startswith("{")]
    if len(blocks) != 1:
        raise AssertionError(f"want one fenced JSON ask, got {len(blocks)}")
    return json.loads(blocks[0])


class SharedChecks(unittest.TestCase):
    def test_digits_outside_fences_skips_fenced_blocks_only(self):
        src = "no digit here\n```json\n{\"at\": 1700000000}\n```\nstep two, not 2\n"
        self.assertEqual(digits_outside_fences(src), ["step two, not 2"])
        self.assertEqual(fenced(src), ['{"at": 1700000000}'])

    def test_an_unclosed_fence_hides_nothing(self):
        self.assertEqual(digits_outside_fences("```\n{\"at\": 1}\n"), ['{"at": 1}'])
        self.assertEqual(fenced("```\n{\"at\": 1}\n"), [])

    def test_the_cap_is_the_tighter_of_the_coach_and_learn_caps(self):
        import test_coach_skill
        import test_learn_skill
        self.assertEqual(SKILL_MAX_LINES, min(test_coach_skill.MAX_LINES, test_learn_skill.MAX_LINES))


class Format(unittest.TestCase):
    def test_frontmatter_parses_and_the_name_matches_the_dir(self):
        fm, rest = frontmatter(text())
        self.assertEqual(fm["name"], SKILL.parent.name)
        self.assertEqual(fm["name"], "chief")
        self.assertTrue(rest.strip())

    def test_the_description_is_use_when_trigger_then_behavior(self):
        desc = frontmatter(text())[0]["description"]
        self.assertRegex(desc, r"^Use when [^.]+\. [A-Z][^.]*\.$")

    def test_under_the_size_cap_the_other_skills_use(self):
        self.assertLessEqual(len(text().split("\n")), SKILL_MAX_LINES)


class Tools(unittest.TestCase):
    def test_every_tool_named_is_in_plugin_yaml(self):
        named = named_tools(text())
        self.assertTrue(named)
        self.assertEqual(sorted(named - set(manifest_list("provides_tools"))), [])

    def test_the_table_names_every_chief_tool(self):
        self.assertEqual(sorted(CHIEF_TOOLS - table_tools(body())), [])


class Never(unittest.TestCase):
    def test_no_clock_time(self):
        self.assertEqual(clock_hits(text()), [])

    def test_no_dosing_words(self):
        self.assertEqual(dosing_hits(text()), [])

    def test_no_digit_outside_a_fenced_example(self):
        self.assertEqual(digits_outside_fences(text()), [])

    def test_no_score_or_grade_offered_as_a_feature(self):
        self.assertEqual(score_as_feature(text()), [])

    def test_event_cues_only(self):
        low = flat(text())
        self.assertIn("event cues", low)
        self.assertIn("never a clock time", low)


class Ask(unittest.TestCase):
    def test_an_ask_goes_to_the_queue_instead_of_a_message(self):
        low = flat(body())
        for phrase in ("append one ask", "asks queue", "instead of messaging him", "never message him directly"):
            self.assertIn(phrase, low)

    def test_the_example_has_only_fields_asks_py_reads(self):
        row = example()
        self.assertEqual(sorted(set(row) - {"id", "kind", "effort", "title", "at", "urgent", "answers"}), [])
        for key in ("id", "kind", "title", "at", "urgent"):
            self.assertIn(key, row)
        self.assertNotIn("delivered_at", row)   # the host sets it, never the agent

    def test_the_example_is_a_peak_decision_that_renders_one_tap(self):
        row = example()
        self.assertEqual(asks.classify(row), asks.PEAK)
        shown = asks.render(row)
        self.assertTrue(one_tap.is_one_tap(shown), shown)
        self.assertEqual(asks.answers(row), one_tap.YES_NO_LATER)
        self.assertEqual(len(shown.split("\n")), 2, shown)   # one title line, one choices line
        self.assertFalse(re.search(r"\bt_[0-9a-f]{6,}\b", shown), shown)

    def test_the_example_delivers_at_peak_and_holds_elsewhere(self):
        row = example()
        peak = decision_window.WindowState(cls="peak", since="wake", source="test", confidence=1.0)
        trough = decision_window.WindowState(cls="trough", since="wake", source="test", confidence=1.0)
        focus = decision_window.WindowState(cls="peak", since="focus_start", source="test", hold_asks=True)
        self.assertEqual(asks.plan([row], peak, 0)[0][1], asks.DELIVER)
        self.assertEqual(asks.plan([row], peak, 1)[0][1], asks.HOLD)
        self.assertEqual(asks.plan([row], trough, 0)[0][1], asks.HOLD)
        self.assertEqual(asks.plan([row], focus, 0)[0][1], asks.HOLD)
        self.assertEqual(asks.plan([dict(row, urgent=True)], focus, 1)[0][1], asks.DELIVER)

    def test_one_line_plain_words_and_a_one_tap_reply(self):
        low = flat(body())
        for phrase in ("one line in plain words", "yes / no / later", "never a card id",
                       "never ask for a typed answer", "later is never a no"):
            self.assertIn(phrase, low)

    def test_kinds_map_to_the_window_asks_py_uses(self):
        low = flat(body())
        for phrase in ("`kind: decision`", "`kind: approval`", "`kind: fyi`", "`effort: deep`", "`urgent: true`"):
            self.assertIn(phrase, low)


class Window(unittest.TestCase):
    def test_limitless_window_and_the_plan_decide(self):
        low = flat(body())
        for phrase in ("call `limitless_window`", "let the plan decide", "decide only at peak",
                       "at most one decision per peak window", "review at trough", "focus block",
                       "unless urgent"):
            self.assertIn(phrase, low)

    def test_quotes_the_asks_labels_limitless_window_returns(self):
        low = flat(body())
        for label in (asks.READY, asks.WAITING, asks.NOTHING):
            self.assertIn(label, low)

    def test_urgent_is_rare_and_never_a_way_round_the_window(self):
        low = flat(body())
        self.assertIn("cannot wait for the next peak", low)
        self.assertIn("never to skip the queue", low)


class Board(unittest.TestCase):
    def test_one_status_board_in_words(self):
        low = flat(body())
        for phrase in ("one status board", "in words", "landed", "waits on him", "blocked", "never a second store"):
            self.assertIn(phrase, low)

    def test_the_board_is_read_from_what_exists(self):
        low = flat(body())
        self.assertIn("rebuilt from the asks queue", low)


class Commit(unittest.TestCase):
    def test_suggest_and_prepare_commit_only_after_his_confirmation(self):
        low = flat(body())
        for phrase in ("suggest and prepare", "only after his confirmation", "no autonomous action"):
            self.assertIn(phrase, low)


if __name__ == "__main__":
    unittest.main()
