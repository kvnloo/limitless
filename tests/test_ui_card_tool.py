"""limitless_card_view: the state card or the week review as one ephemeral HTML card (synthetic fixtures only)."""
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card_view, jobs, jobs_runner, one_tap, plugin, ui_card  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
NOW = 1894708800.0          # the fixture's synthetic "now" (as tests/test_card.py)
TODAY = date(2030, 1, 15)
UTC = timezone.utc
WNOW = 2_000_000_000.0      # the week-review tests' arbitrary epoch (as tests/test_week_review.py)
WTODAY = datetime.fromtimestamp(WNOW, UTC).date()


def visible(html):
    return re.sub(r"<[^>]*>", "", re.search(r"(?s)<body>(.*)</body>", html).group(1))


def week(days_back, habit="Synthetic habit", **kw):
    at = datetime.fromtimestamp(WNOW - 3600, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return dict({"at": at, "week_of": (WTODAY - timedelta(days=days_back)).isoformat(), "habit": habit,
                 "checkins": {}}, **kw)


class FakePush:
    def __init__(self):
        self.calls = []

    def __call__(self, title, body, once=None):
        self.calls.append((title, body, once))
        return "telegram"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        shutil.copytree(FIX, self.st)
        self.cards = self.root / "cards"
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def view(self, kind="state", now=NOW, today=TODAY, **env):
        return card_view.view(self.st, now, today, kind, env=dict(self.env, **env), home=self.root)


class StateCard(Base):
    def test_envelope_shape(self):
        r = self.view()
        self.assertEqual(set(r["value"]), {"path", "rows", "dropped"})
        self.assertEqual((r["modality"], r["age_h"]), ("derived", None))
        self.assertIn(r["evidence_tier"], ("direct", "indirect", "stale", "none"))
        self.assertGreater(r["value"]["rows"], 0)

    def test_label_is_t1_words_with_the_row_count(self):
        r = self.view()
        self.assertEqual(r["label"]["tier"], "T1")
        self.assertEqual(r["label"]["label"], f"a state card with {card_view.count_words(r['value']['rows'])}")
        self.assertNotRegex(r["label"]["label"], r"\d")

    def test_count_words(self):
        self.assertEqual([card_view.count_words(n) for n in (0, 1, 2, 3, 8)],
                         ["no rows", "one row", "two rows", "three rows", "eight rows"])

    def test_no_card_dir_renders_only_writes_nothing_and_says_why(self):
        r = self.view()
        self.assertIsNone(r["value"]["path"])
        self.assertEqual(r["note"], ui_card.NO_DIR)
        self.assertFalse(self.cards.exists())

    def test_card_dir_writes_one_0600_card(self):
        r = self.view(LIMITLESS_CARD_DIR=str(self.cards))
        p = Path(r["value"]["path"])
        self.assertEqual(p.parent, self.cards)
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        html = p.read_text(encoding="utf-8")
        self.assertEqual(html.count('class="row '), r["value"]["rows"])
        self.assertNotRegex(visible(html), r"\d")
        self.assertNotIn("note", r)

    def test_rows_are_the_state_card_lines_without_its_model_header(self):
        r = self.view(LIMITLESS_CARD_DIR=str(self.cards))
        html = Path(r["value"]["path"]).read_text(encoding="utf-8")
        self.assertNotIn("[limitless]", html)
        self.assertIn("window:", html)

    def test_no_raw_number_even_under_the_raw_opt_in(self):
        r = self.view(LIMITLESS_CARD_DIR=str(self.cards), LIMITLESS_RAW_IN_PROMPT="1")
        self.assertNotRegex(visible(Path(r["value"]["path"]).read_text(encoding="utf-8")), r"\d")

    def test_a_line_with_a_digit_is_dropped_and_counted(self):
        h = json.loads((self.st / "habit.json").read_text())
        h["habit"] = "Walk 10 minutes"
        (self.st / "habit.json").write_text(json.dumps(h))
        r = self.view(LIMITLESS_CARD_DIR=str(self.cards))
        self.assertGreaterEqual(r["value"]["dropped"], 1)
        html = Path(r["value"]["path"]).read_text(encoding="utf-8")
        self.assertNotIn("Walk", html)
        self.assertNotIn("#", visible(html), "a masked number is not shown either")

    def test_mode_line_is_a_row(self):
        (self.st / "mode.json").write_text(json.dumps({"mode": "focused"}))
        r = self.view(LIMITLESS_CARD_DIR=str(self.cards))
        html = Path(r["value"]["path"]).read_text(encoding="utf-8")
        self.assertIn('<li class="row held"><span class="chip">held</span><span class="text">focused mode', html)

    def test_same_state_same_file(self):
        a = self.view(LIMITLESS_CARD_DIR=str(self.cards))["value"]["path"]
        b = self.view(LIMITLESS_CARD_DIR=str(self.cards))["value"]["path"]
        self.assertEqual(a, b)
        self.assertEqual(len(os.listdir(self.cards)), 1)

    def test_missing_state_dir_and_bad_kind(self):
        self.assertIsNone(self.view("other")["value"])
        self.assertIn("kind", self.view("other")["reason"])
        shutil.rmtree(self.st)
        self.assertIsNone(self.view()["value"])


class WeekCard(Base):
    def setUp(self):
        super().setUp()
        for f in self.st.iterdir():
            f.unlink()
        days = {(WTODAY - timedelta(days=6)).isoformat(): "Done", (WTODAY - timedelta(days=1)).isoformat(): "No"}
        self.habit = week(6, checkins=days)
        (self.st / "habit.json").write_text(json.dumps(self.habit))

    def test_body_is_what_the_week_review_push_says(self):
        (self.st / "events.jsonl").write_text(json.dumps({"event": "habit_cue", "at": WNOW - 60}) + "\n")
        push = FakePush()
        jobs_runner.run_once(self.st, WNOW, push=push, dry_run=False, env=self.env, home=self.root, tz=UTC)
        sent = [b for t, b, _ in push.calls if t == "Week review"]
        self.assertEqual(len(sent), 1)
        self.assertEqual(jobs_runner.week_review_body(self.st, self.habit, {}, self.env, self.root, UTC, WTODAY),
                         sent[0])

    def test_week_card_rows_are_the_review_lines_without_the_ask(self):
        r = self.view("week", now=WNOW, today=WTODAY, LIMITLESS_CARD_DIR=str(self.cards))
        html = Path(r["value"]["path"]).read_text(encoding="utf-8")
        self.assertNotIn(one_tap.choices_line(jobs.WEEK_REVIEW.answers), html)
        self.assertNotRegex(visible(html), r"\d")
        self.assertEqual(r["value"]["dropped"], 1, "the N of M logged days line carries digits: dropped")
        self.assertIn(ui_card.TITLES["week"], html)
        self.assertEqual(r["label"]["label"], f"a week card with {card_view.count_words(r['value']['rows'])}")
        self.assertEqual(r["evidence_tier"], "direct")

    def test_no_habit_week_still_renders(self):
        (self.st / "habit.json").unlink()
        r = self.view("week", now=WNOW, today=WTODAY)
        self.assertEqual(r["value"]["rows"], 1)
        self.assertEqual(r["evidence_tier"], "none")


class Plugin(unittest.TestCase):
    def test_tool_is_registered_with_kind(self):
        schema, fn, _ = plugin.TOOLS["limitless_card_view"]
        self.assertEqual(schema["parameters"]["properties"]["kind"]["enum"], ["state", "week"])
        self.assertIn("never", schema["description"])

    def test_handler_returns_the_envelope(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        st = Path(tmp.name) / "state"
        shutil.copytree(FIX, st)
        env = {"LIMITLESS_STATE": str(st), "LIMITLESS_CONFIG": str(Path(tmp.name) / "none.json")}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("LIMITLESS_CARD_DIR", None)
            out = json.loads(plugin._handler(plugin.TOOLS["limitless_card_view"][1], "limitless_card_view")(
                {"kind": "state"}))
        self.assertEqual(out["modality"], "derived")
        self.assertIsNone(out["value"]["path"])
        self.assertTrue(out["label"]["label"].startswith("a state card with "))


if __name__ == "__main__":
    unittest.main()
