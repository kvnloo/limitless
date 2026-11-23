"""limitless/prompt_rules.py: the plugin's standing rules as one short, static, data-free system prompt
section (``limitless.rules``): no digit, no clock time, no dosing word, the same bytes every session."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_coach_skill import CLOCK, DOSING  # noqa: E402

from limitless import prompt_rules  # noqa: E402

# the host's section id rule (hermes_cli/plugins_context.py): 1-128 lowercase letters, digits, '.', '_', '-'
ID_RE = re.compile(r"^[a-z0-9._-]{1,128}$")
MAX_LINES = 9   # a one-line heading and eight short rules


class Content(unittest.TestCase):
    def test_the_id_is_limitless_rules_and_valid(self):
        self.assertEqual(prompt_rules.SECTION_ID, "limitless.rules")
        self.assertRegex(prompt_rules.SECTION_ID, ID_RE)

    def test_it_is_short(self):
        c = prompt_rules.CONTENT
        self.assertIsInstance(c, str)
        self.assertLessEqual(len(c.splitlines()), MAX_LINES)
        self.assertLess(len(c), 800)
        self.assertLessEqual(len(c), prompt_rules.MAX_CHARS)
        for ln in c.splitlines():
            self.assertLessEqual(len(ln), 110, ln)

    def test_no_digit_so_it_stays_t1(self):
        self.assertEqual([ch for ch in prompt_rules.CONTENT if ch.isdigit()], [])

    def test_no_clock_time_and_no_dosing_word(self):
        c = prompt_rules.CONTENT
        for pat in CLOCK:
            self.assertIsNone(pat.search(c), pat.pattern)
        words = set(re.findall(r"[a-z]+", c.lower()))
        for w in DOSING:
            if " " in w:
                self.assertNotIn(w, c.lower())
            else:
                self.assertNotIn(w, words)

    def test_the_same_bytes_every_call(self):
        a, b = prompt_rules.content(), prompt_rules.content()
        self.assertEqual(a.encode("utf-8"), b.encode("utf-8"))
        self.assertIs(a, prompt_rules.CONTENT)

    def test_it_names_every_rule(self):
        c = prompt_rules.CONTENT.lower()
        for phrase in ("labels", "opted in", "unknown is never zero", "yes in this turn", "one habit a week",
                       "unlogged", "events, never a clock time", "jobs and send gate", "never diagnose",
                       "capability score", "limitless:coach"):
            self.assertIn(phrase, c)

    def test_the_module_reads_no_state_and_no_clock(self):
        src = Path(prompt_rules.__file__).read_text()
        for banned in ("import time", "import datetime", "from datetime", "StateReader", "state_dir",
                       "open(", "read_text", "environ"):
            self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main()
