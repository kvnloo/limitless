"""limitless/prompt_rules.py: the plugin's standing rules as one short, static, data-free system prompt
section (``limitless.rules``): no digit, no clock time, no dosing word, the same bytes every session."""
import json
import logging
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


class SectionCtx:
    """A host with register_system_prompt_section(id, content, *, position, max_chars) and its checks."""

    def __init__(self):
        self.sections = []

    def register_system_prompt_section(self, id, content, *, position="after_memory", max_chars=None):
        if not isinstance(id, str) or not ID_RE.match(id):
            raise ValueError(f"invalid section id {id!r}")
        if any(s["id"] == id for s in self.sections):
            raise ValueError(f"duplicate section id {id!r}")
        if not (isinstance(content, str) or callable(content)):
            raise TypeError("content must be a str or a callable")
        self.sections.append({"id": id, "content": content, "position": position, "max_chars": max_chars})


def _ours(cm):
    return [r for r in cm.records if r.name.endswith("limitless.prompt_rules")]


class Config(unittest.TestCase):
    def run_register(self, ctx, cfg):
        with self.assertLogs(level="DEBUG") as cm:
            logging.getLogger("limitless-prompt-rules-test").debug("anchor")   # assertLogs needs one record
            prompt_rules.register(ctx, cfg)
        return [r.getMessage() for r in _ours(cm)]

    def test_on_by_default(self):
        for cfg in ({}, {"prompt_rules": True}, {"other": False}):
            with self.subTest(cfg=cfg):
                self.assertTrue(prompt_rules.enabled(cfg))
                ctx = SectionCtx()
                self.assertEqual(self.run_register(ctx, cfg), [])
                self.assertEqual([s["id"] for s in ctx.sections], [prompt_rules.SECTION_ID])

    def test_false_turns_it_off_with_one_content_free_line(self):
        for cfg in ({"prompt_rules": False}, {"prompt_rules": "off"}):
            with self.subTest(cfg=cfg):
                self.assertFalse(prompt_rules.enabled(cfg))
                ctx = SectionCtx()
                self.assertEqual(self.run_register(ctx, cfg), [prompt_rules.DISABLED])
                self.assertEqual(ctx.sections, [])
        self.assertFalse(any(c.isdigit() for c in prompt_rules.DISABLED))

    def test_no_config_reads_the_host_config(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "config.json"
        path.write_text(json.dumps({"prompt_rules": False}))
        ctx = SectionCtx()
        with mock.patch.dict(os.environ, {"LIMITLESS_CONFIG": str(path)}, clear=True):
            self.assertEqual(self.run_register(ctx, None), [prompt_rules.DISABLED])
        self.assertEqual(ctx.sections, [])


if __name__ == "__main__":
    unittest.main()
