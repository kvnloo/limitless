"""register(ctx) offers limitless:learn beside the plugin's other skills (limitless:coach, limitless:chief) to a host
with register_skill; without it one content-free line in all; one skill the host refuses never stops the others."""
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skill_checks import frontmatter  # noqa: E402
from test_coach_register import SkillCtx, _ours  # noqa: E402
from test_plugin import FakeCtx, fake_ctx_hooks, load_plugin, manifest_list  # noqa: E402

from limitless import coach_skill  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class RefusesOne(SkillCtx):
    """A host that raises for one named skill and takes the rest."""

    def __init__(self, refused, exc):
        super().__init__()
        self.refused, self.exc, self.calls = refused, exc, []

    def register_skill(self, name, path, description="", frontmatter=None):
        self.calls.append(name)
        if name == self.refused:
            raise self.exc
        super().register_skill(name, path, description=description, frontmatter=frontmatter)


class Register(unittest.TestCase):
    def register(self, ctx, skills_dir=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = {"LIMITLESS_CONFIG": str(Path(tmp.name) / "absent.json")}
        mod = load_plugin()
        loaded = sys.modules[mod.__name__ + ".limitless.coach_skill"]   # the plugin's own copy of the module
        with mock.patch.dict(os.environ, env, clear=True), self.assertLogs(level="DEBUG") as cm, \
                mock.patch.object(loaded, "SKILLS_DIR", skills_dir or loaded.SKILLS_DIR):
            logging.getLogger("limitless-learn-test").debug("anchor")   # assertLogs needs one record
            mod.register(ctx)
        return _ours(cm)

    def assert_rest_registered(self, ctx):
        self.assertEqual(sorted(ctx.tools), sorted(manifest_list("provides_tools")))
        self.assertEqual(sorted(ctx.hooks), fake_ctx_hooks())

    def test_the_skill_names_are_a_small_tuple_with_a_file_each(self):
        self.assertEqual(coach_skill.NAMES, ("coach", "learn", "chief"))
        for name in coach_skill.NAMES:
            p = coach_skill.path(name)
            self.assertEqual(p.resolve(), (ROOT / "skills" / name / "SKILL.md").resolve())
            self.assertTrue(p.is_file(), name)
            self.assertEqual(frontmatter(p.read_text())[0]["name"], name)

    def test_a_host_with_register_skill_gets_both_skills(self):
        ctx = SkillCtx()
        lines = self.register(ctx)
        self.assertEqual([s["name"] for s in ctx.skills], list(coach_skill.NAMES))
        for s in ctx.skills:
            self.assertTrue(s["path"].is_file(), s["name"])
            self.assertEqual(s["path"].parent.name, s["name"])
            self.assertEqual(s["description"], frontmatter(s["path"].read_text())[0]["description"])
        self.assertEqual([r.getMessage() for r in lines if r.levelno >= logging.WARNING], [])
        self.assert_rest_registered(ctx)

    def test_a_host_without_it_gets_one_line_in_all(self):
        ctx = FakeCtx()
        lines = self.register(ctx)
        self.assertEqual([r.getMessage() for r in lines], [coach_skill.NO_HOST])
        self.assertFalse(any(c.isdigit() for c in coach_skill.NO_HOST))
        self.assert_rest_registered(ctx)

    def test_one_raising_call_still_lets_the_other_register(self):
        for refused, kept in (("coach", ["learn", "chief"]), ("learn", ["coach", "chief"])):
            for exc in (RuntimeError("host refused"), ValueError("bad name"), FileNotFoundError("gone")):
                with self.subTest(refused=refused, exc=type(exc).__name__):
                    ctx = RefusesOne(refused, exc)
                    lines = self.register(ctx)
                    self.assertEqual(ctx.calls, list(coach_skill.NAMES))
                    self.assertEqual([s["name"] for s in ctx.skills], kept)
                    self.assertEqual([(r.levelno, r.getMessage()) for r in lines],
                                     [(logging.WARNING, coach_skill.HOST_FAILED)])
                    self.assert_rest_registered(ctx)

    def test_one_missing_skill_file_still_lets_the_other_register(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        only = Path(tmp.name) / "learn"
        only.mkdir()
        (only / "SKILL.md").write_text((ROOT / "skills" / "learn" / "SKILL.md").read_text())
        ctx = SkillCtx()
        lines = self.register(ctx, skills_dir=Path(tmp.name))
        self.assertEqual([s["name"] for s in ctx.skills], ["learn"])
        self.assertEqual([r.getMessage() for r in lines], [coach_skill.HOST_FAILED] * (len(coach_skill.NAMES) - 1))
        self.assert_rest_registered(ctx)

    def test_plugin_register_still_works_without_register_skill(self):
        ctx = FakeCtx()
        self.assertFalse(hasattr(ctx, "register_skill"))
        self.register(ctx)
        self.assert_rest_registered(ctx)


if __name__ == "__main__":
    unittest.main()
