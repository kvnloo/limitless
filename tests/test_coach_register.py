"""register(ctx) offers the coach skill (skills/coach/SKILL.md), with the plugin's other skills, to a host with
register_skill (feature detection); without it one content-free line and nothing else; a host that raises never
breaks the other registrations."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
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

from test_coach_skill import SKILL, frontmatter  # noqa: E402
from test_plugin import FakeCtx, fake_ctx_hooks, load_plugin, manifest_list  # noqa: E402

from limitless import coach_skill, schedule_cards  # noqa: E402

METHOD = "register_skill"


class SkillCtx(FakeCtx):
    """A host with the documented register_skill(name, path, description="", frontmatter=None) and its checks."""

    def __init__(self):
        super().__init__()
        self.skills = []

    def register_skill(self, name, path, description="", frontmatter=None):
        if ":" in name or not re.match(r"^[a-zA-Z0-9_-]+$", name):
            raise ValueError(f"Invalid skill name '{name}'")
        if not Path(path).exists():
            raise FileNotFoundError(f"SKILL.md not found at {path}")
        self.skills.append({"name": name, "path": Path(path), "description": description,
                            "frontmatter": frontmatter})


class RaisingSkillCtx(FakeCtx):
    def __init__(self, exc):
        super().__init__()
        self.exc, self.cards = exc, []

    def register_skill(self, name, path, description="", frontmatter=None):
        raise self.exc

    def register_schedule_card(self, card):
        self.cards.append(card)


class NotCallableCtx(FakeCtx):
    register_skill = None


def _ours(cm):
    return [r for r in cm.records if r.name.endswith("limitless.coach_skill")]


class Register(unittest.TestCase):
    def register(self, ctx, skills_dir=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = {"LIMITLESS_CONFIG": str(Path(tmp.name) / "absent.json")}
        mod = load_plugin()
        loaded = sys.modules[mod.__name__ + ".limitless.coach_skill"]   # the plugin's own copy of the module
        with mock.patch.dict(os.environ, env, clear=True), self.assertLogs(level="DEBUG") as cm, \
                mock.patch.object(loaded, "SKILLS_DIR", skills_dir or loaded.SKILLS_DIR):
            logging.getLogger("limitless-coach-test").debug("anchor")   # assertLogs needs one record
            mod.register(ctx)
        return _ours(cm)

    def assert_rest_registered(self, ctx):
        self.assertEqual(sorted(ctx.tools), sorted(manifest_list("provides_tools")))
        self.assertEqual(sorted(ctx.hooks), fake_ctx_hooks())

    def test_the_names_are_the_documented_ones(self):
        self.assertEqual(coach_skill.HOST_METHOD, METHOD)
        self.assertIn("coach", coach_skill.NAMES)
        self.assertEqual(coach_skill.path("coach").resolve(), SKILL.resolve())

    def test_a_host_with_register_skill_gets_the_coach_skill(self):
        ctx = SkillCtx()
        lines = self.register(ctx)
        self.assertEqual(len(ctx.skills), len(coach_skill.NAMES))
        s = [s for s in ctx.skills if s["name"] == "coach"][0]
        self.assertEqual(s["name"], "coach")
        self.assertEqual(s["path"].resolve(), SKILL.resolve())
        self.assertTrue(s["path"].is_file())
        self.assertEqual(s["description"], frontmatter(SKILL.read_text())[0]["description"])
        self.assertEqual([r.getMessage() for r in lines if r.levelno >= logging.WARNING], [])
        self.assert_rest_registered(ctx)

    def test_the_description_is_the_frontmatter_one(self):
        self.assertEqual(coach_skill.description(coach_skill.path("coach")),
                         frontmatter(SKILL.read_text())[0]["description"])

    def test_a_host_without_it_gets_one_content_free_line_and_nothing_else(self):
        ctx = FakeCtx()
        self.assertFalse(hasattr(ctx, METHOD))
        lines = self.register(ctx)
        self.assertEqual([r.getMessage() for r in lines], [coach_skill.NO_HOST])
        self.assertFalse(any(c.isdigit() for c in coach_skill.NO_HOST))
        self.assert_rest_registered(ctx)

    def test_a_non_callable_attribute_is_no_host(self):
        ctx = NotCallableCtx()
        lines = self.register(ctx)
        self.assertEqual([r.getMessage() for r in lines], [coach_skill.NO_HOST])
        self.assert_rest_registered(ctx)

    def test_a_raising_host_never_breaks_the_other_registrations(self):
        for exc in (RuntimeError("host refused"), ValueError("bad name"), FileNotFoundError("gone")):
            with self.subTest(exc=type(exc).__name__):
                ctx = RaisingSkillCtx(exc)
                lines = self.register(ctx)
                self.assertEqual([(r.levelno, r.getMessage()) for r in lines],
                                 [(logging.WARNING, coach_skill.HOST_FAILED)] * len(coach_skill.NAMES))
                self.assertNotIn(str(exc), coach_skill.HOST_FAILED)
                self.assert_rest_registered(ctx)
                self.assertEqual(ctx.cards, schedule_cards.cards())

    def test_a_missing_skill_file_reaches_the_host_and_is_caught(self):
        ctx = SkillCtx()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        lines = self.register(ctx, skills_dir=Path(tmp.name) / "absent")
        self.assertEqual(ctx.skills, [])
        self.assertEqual([r.getMessage() for r in lines], [coach_skill.HOST_FAILED] * len(coach_skill.NAMES))
        self.assert_rest_registered(ctx)


if __name__ == "__main__":
    unittest.main()
