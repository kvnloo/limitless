"""Weekly target wording: the habit check-in may say "target reached this week"; nothing user-facing in the
habit or week-review code says streak, missed, failed or broke. Synthetic habit weeks only; nothing sends.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import ast
import inspect
import itertools
import os
import re
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import (habit_replies, habit_start, jobs, jobs_runner, one_tap, passive_habit,  # noqa: E402
                       weekly_target)

START = date(2031, 3, 3)
BANNED = re.compile(r"(?i)\b(streaks?|missed|fail\w*|broke)\b")
REPLY = "Reply: Done / No / Skip"
QUESTION = "Did you do it today: Synthetic habit?"


def habit(*words, **kw):
    c = {(START + timedelta(days=i)).isoformat(): w for i, w in enumerate(words) if w is not None}
    return dict({"habit": "Synthetic habit", "week_of": START.isoformat(), "checkins": c}, **kw)


class CheckinWording(unittest.TestCase):
    def test_reached_adds_one_line_before_the_choices(self):
        got = jobs_runner.body(jobs.HABIT_CHECKIN, habit("Done", "Done", "No", "Done", "Done"))
        self.assertEqual(got.splitlines(), [QUESTION, weekly_target.CHECKIN_REACHED, REPLY])
        self.assertIn("target reached this week", got.lower())
        self.assertTrue(one_tap.is_one_tap(got))

    def test_not_reached_says_nothing_about_a_target(self):
        for h in (habit(), habit("Done", "Done", "Done"), habit("No", "Skipped", None, "No"), {}, None):
            got = jobs_runner.body(jobs.HABIT_CHECKIN, h)
            self.assertNotIn("target", got.lower(), h)
            self.assertEqual(len(got.splitlines()), 2, got)

    def test_target_days_changes_only_the_words(self):
        h = habit("Done", "Done")
        self.assertNotIn(weekly_target.CHECKIN_REACHED, jobs_runner.body(jobs.HABIT_CHECKIN, h))
        self.assertIn(weekly_target.CHECKIN_REACHED, jobs_runner.body(jobs.HABIT_CHECKIN, h, target_days=2))

    def test_sync_done_days_count(self):
        synced = {(START + timedelta(days=i)).isoformat(): "met" for i in range(4)}
        got = jobs_runner.body(jobs.HABIT_CHECKIN, habit(), synced=synced)
        self.assertIn(weekly_target.CHECKIN_REACHED, got.splitlines())

    def test_checkin_line_is_digit_free(self):
        self.assertFalse(re.search(r"\d", weekly_target.CHECKIN_REACHED))


def _strings(mod, only=None):
    """Every string constant in ``mod`` that is not a docstring (or, with ``only``, inside those functions)."""
    tree = ast.parse(inspect.getsource(mod))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                docs.add(id(body[0].value))
    roots = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in only] if only else [tree]
    out = []
    for root in roots:
        for node in ast.walk(root):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                out.append((node.lineno, node.value))
    return out


class NoPunishingWords(unittest.TestCase):
    # The sync's input vocabulary (habit1.jsonl verdicts) is read, never shown: SYNC_WORDS maps it to No.
    INPUT_WORDS = {jobs: {"missed"}}

    def test_static_strings(self):
        mods = [(habit_replies, None), (habit_start, None), (passive_habit, None), (weekly_target, None),
                (jobs, None),
                (jobs_runner, {"body", "week_passive", "week_review_verdict", "first_hour_wake"})]
        hits = []
        for mod, only in mods:
            allowed = self.INPUT_WORDS.get(mod, set())
            for line, s in _strings(mod, only):
                if s not in allowed and BANNED.search(s):
                    hits.append(f"{mod.__name__}:{line}: {s!r}")
        self.assertEqual(hits, [], "\n".join(hits))
        self.assertIn("missed", jobs.SYNC_WORDS)   # the allowed input word really is only an input key

    def test_module_level_texts(self):
        texts = [jobs_runner.BREAK_BODY, *jobs_runner._BODY.values(), jobs.NO_WEEK, *weekly_target.LABELS,
                 weekly_target.CHECKIN_REACHED, passive_habit.NOT_ENOUGH, passive_habit.NOT_STARTED]
        self.assertEqual([t for t in texts if BANNED.search(t)], [])

    def test_rendered_habit_and_review_texts(self):
        """Every check-in and week review body over all Done / No / Skipped / no-answer weeks (habit lines only)."""
        texts = set()
        for words in itertools.product(("Done", "No", "Skipped", None), repeat=7):
            if words.count(None) not in (0, 3, 7) and words.count("Done") not in (0, 4, 7):
                continue                                  # a spread of weeks, not all 16384
            for target in (1, 4, 7):
                h = habit(*words)
                texts.add(jobs_runner.body(jobs.HABIT_CHECKIN, h, target_days=target))
                texts.add(jobs_runner.body(jobs.WEEK_REVIEW, h, target_days=target))
                for t in range(9):
                    p = weekly_target.progress(h["checkins"], START, START + timedelta(days=t), target)
                    texts.add(p["label"]["label"])
        for h in (None, {}, {"habit": " "}, habit(decision="Drop")):
            texts.add(jobs_runner.body(jobs.HABIT_CHECKIN, h))
            texts.add(jobs_runner.body(jobs.WEEK_REVIEW, h))
            texts.add(jobs.week_review_text(h))
        self.assertGreater(len(texts), 10)
        self.assertEqual([t for t in texts if BANNED.search(t)], [])


if __name__ == "__main__":
    unittest.main()
