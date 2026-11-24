"""overnight.py: the wind-down plan line, the wake brief's landed line and the limitless_overnight tool.

Synthetic lane names only. Counts are words (labeler.count_word); no digit and no item name ever reaches
a line or a label. No dir configured is unknown: no line, value None.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import catchup, labeler, overnight, plugin, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0
WIND = NOW - 9 * H          # last night's wind-down event
FIELDS = {"value", "modality", "age_h", "evidence_tier", "label"}
NAMES = ("secret-project-alpha", "launch-plan-beta", "tax-return-gamma", "move-house-delta", "pitch-deck-x",
         "refactor-omega", "grant-draft-zeta")


def item(name, status, mtime=NOW - H):
    return {"name": name, "status": status, "mtime": mtime}


class CountWord(unittest.TestCase):
    def test_the_labeler_owns_the_count_words_and_catchup_uses_them(self):
        for n, w in ((None, "unknown"), (0, "none"), (1, "one"), (2, "a few"), (4, "a few"), (5, "many"),
                     (40, "many")):
            self.assertEqual(labeler.count_word(n), w)
            self.assertEqual(catchup.count_word(n), w)


class PlanLine(unittest.TestCase):
    def test_running_and_queued_in_words(self):
        items = [item("a", "running"), item("b", "running"), item("c", "queued"), item("d", "queued"),
                 item("e", "queued"), item("f", "done"), item("g", "failed")]
        self.assertEqual(overnight.plan_line(items), "Overnight: a few tasks running, a few queued")

    def test_one_task_and_nothing_queued(self):
        self.assertEqual(overnight.plan_line([item("a", "running")]), "Overnight: one task running, nothing queued")

    def test_nothing_running_many_queued(self):
        items = [item(f"q{i}", "queued") for i in range(7)]
        self.assertEqual(overnight.plan_line(items), "Overnight: nothing running, many queued")

    def test_empty_queue_says_so(self):
        self.assertEqual(overnight.plan_line([]), "Overnight: nothing running or queued")
        self.assertEqual(overnight.plan_line([item("a", "done")]), "Overnight: nothing running or queued")

    def test_no_dir_configured_is_no_line(self):
        self.assertEqual(overnight.plan_line(None), "")


class LandedLine(unittest.TestCase):
    def test_counts_only_items_finished_after_the_wind_down(self):
        items = [item("a", "done"), item("b", "done"), item("c", "failed"),
                 item("old", "done", WIND - H), item("older", "failed", WIND - 2 * H)]
        self.assertEqual(overnight.landed_line(items, WIND), "Overnight: a few done, one failed")

    def test_none_failed(self):
        self.assertEqual(overnight.landed_line([item("a", "done")], WIND), "Overnight: one done, none failed")

    def test_still_running_is_added(self):
        items = [item("a", "done"), item("b", "running")]
        self.assertEqual(overnight.landed_line(items, WIND), "Overnight: one done, none failed, one still running")

    def test_empty_queue_is_nothing_ran(self):
        self.assertEqual(overnight.landed_line([], WIND), "Overnight: nothing ran")
        self.assertEqual(overnight.landed_line([item("old", "done", WIND - H), item("q", "queued")], WIND),
                         "Overnight: nothing ran")

    def test_nothing_finished_but_some_running(self):
        self.assertEqual(overnight.landed_line([item("r", "running")], WIND),
                         "Overnight: nothing finished, one still running")

    def test_no_dir_configured_is_no_line(self):
        self.assertEqual(overnight.landed_line(None, WIND), "")

    def test_unknown_since_counts_every_finished_item(self):
        items = [item("a", "done", 1.0), item("b", "failed", 2.0)]
        for since in (None, "last night", float("nan"), True):
            self.assertEqual(overnight.landed_line(items, since), "Overnight: one done, one failed")


class Since(unittest.TestCase):
    def test_the_latest_wind_down_at_or_before_now(self):
        evs = [{"event": "wind_down", "at": NOW - 30 * H}, {"event": "wind_down", "at": WIND},
               {"event": "wake", "at": NOW - H}, {"event": "wind_down", "at": NOW + H}]
        self.assertEqual(overnight.since(evs, NOW), WIND)

    def test_no_wind_down_is_one_awake_day_back(self):
        self.assertEqual(overnight.since([{"event": "wake", "at": NOW - H}], NOW),
                         NOW - overnight.MAX_AWAKE_H * H)
        self.assertEqual(overnight.since([{"event": "wind_down", "at": NOW - 30 * H}], NOW),
                         NOW - overnight.MAX_AWAKE_H * H)
        self.assertEqual(overnight.since(None, NOW), NOW - overnight.MAX_AWAKE_H * H)


class StateBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_STATE": str(self.st)}
        self.q = self.st / "lanes"

    def configure(self):
        self.cfg.write_text(json.dumps({"work_queue_dir": "lanes"}))

    def put(self, status_dir, name, mtime):
        p = self.q / status_dir / f"{name}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("synthetic body that is never read\n")
        os.utime(p, (mtime, mtime))

    def wind_down(self, at=WIND):
        (self.st / "events.jsonl").write_text(json.dumps({"event": "wind_down", "at": at}) + "\n")

    def busy_night(self):
        self.configure()
        self.wind_down()
        self.q.mkdir(parents=True, exist_ok=True)
        for sub in ("queue", "running", "done", "failed"):
            (self.q / sub).mkdir(exist_ok=True)
        self.put("running", NAMES[0], NOW - 2 * H)
        self.put("queue", NAMES[1], NOW - 8 * H)
        self.put("queue", NAMES[2], NOW - 8 * H)
        self.put("done", NAMES[3], NOW - 3 * H)
        self.put("done", NAMES[4], NOW - 4 * H)
        self.put("failed", NAMES[5], NOW - 0.5 * H)
        self.put("done", NAMES[6], WIND - 5 * H)           # finished before the wind-down: not landed

    def tool(self):
        return tools.overnight(StateReader(self.st), NOW, env=self.env, home=self.root)


class FromState(StateBase):
    def test_plan_and_landed_from_the_state_dir(self):
        self.busy_night()
        self.assertEqual(overnight.plan_for(self.st, NOW, env=self.env, home=self.root),
                         "Overnight: one task running, a few queued")
        self.assertEqual(overnight.landed_for(self.st, NOW, env=self.env, home=self.root),
                         "Overnight: a few done, one failed, one still running")

    def test_no_dir_configured_or_missing_dir_is_no_line(self):
        self.wind_down()
        self.assertEqual(overnight.plan_for(self.st, NOW, env=self.env, home=self.root), "")
        self.assertEqual(overnight.landed_for(self.st, NOW, env=self.env, home=self.root), "")
        self.configure()                                     # configured, but the dir is not there: unknown
        self.assertEqual(overnight.plan_for(self.st, NOW, env=self.env, home=self.root), "")
        self.assertEqual(overnight.landed_for(self.st, NOW, env=self.env, home=self.root), "")

    def test_empty_queue_dir_is_nothing_ran(self):
        self.configure()
        self.wind_down()
        self.q.mkdir()
        self.assertEqual(overnight.landed_for(self.st, NOW, env=self.env, home=self.root), "Overnight: nothing ran")
        self.assertEqual(overnight.plan_for(self.st, NOW, env=self.env, home=self.root),
                         "Overnight: nothing running or queued")

    def test_unreadable_state_is_no_line_never_a_traceback(self):
        self.busy_night()
        with mock.patch.object(StateReader, "work_items", side_effect=RuntimeError("boom")):
            self.assertEqual(overnight.plan_for(self.st, NOW, env=self.env, home=self.root), "")
            self.assertEqual(overnight.landed_for(self.st, NOW, env=self.env, home=self.root), "")


class Tool(StateBase):
    def test_envelope_with_counts_and_a_label(self):
        self.busy_night()
        out = self.tool()
        self.assertTrue(FIELDS <= set(out), out)
        self.assertEqual(out["value"], {"running": 1, "queued": 2, "done_since": 2, "failed_since": 1})
        self.assertEqual(out["modality"], "measured")
        self.assertEqual(out["age_h"], 0.5)                  # the newest item changed half an hour ago
        self.assertEqual(out["evidence_tier"], "direct")
        self.assertEqual(out["label"], {"label": "one task running, a few queued; a few done, one failed, "
                                                 "one still running", "tier": "T1", "modality": "measured"})

    def test_no_dir_configured_is_missing_with_a_reason_not_zero(self):
        out = self.tool()
        self.assertIsNone(out["value"])
        self.assertIn("work_queue_dir", out["reason"])
        self.configure()
        out = self.tool()
        self.assertIsNone(out["value"])
        self.assertNotIn(str(self.root), out["reason"])     # reasons never echo the path

    def test_read_only(self):
        self.busy_night()
        before = sorted((str(p), p.stat().st_mtime) for p in self.root.rglob("*"))
        self.tool()
        self.assertEqual(sorted((str(p), p.stat().st_mtime) for p in self.root.rglob("*")), before)

    def test_through_the_plugin_handler(self):
        self.busy_night()
        self.assertIn("limitless_overnight", plugin.TOOLS)
        with mock.patch.dict(os.environ, self.env), mock.patch("time.time", return_value=NOW):
            res = json.loads(plugin._handler(plugin.TOOLS["limitless_overnight"][1], "limitless_overnight")({}))
        self.assertEqual(res["value"]["failed_since"], 1)
        self.assertEqual(res["label"]["tier"], "T1")


class NoDigitsNoNames(StateBase):
    """Lane names can carry project words: the person's messages and the label get counts only."""

    def assert_clean(self, text):
        self.assertEqual(re.findall(r"\d", text), [], text)
        for n in NAMES:
            for word in n.split("-"):
                if len(word) > 1:
                    self.assertNotIn(word, text, text)

    def test_lines_and_label_over_many_shapes(self):
        for k in range(0, 9):
            items = [item(NAMES[i % len(NAMES)], st) for i, st in
                     enumerate(["running", "queued", "done", "failed"] * k)]
            self.assert_clean(overnight.plan_line(items))
            self.assert_clean(overnight.landed_line(items, WIND))
            self.assert_clean(overnight.label(items, WIND)["label"])

    def test_from_state_and_through_the_tool(self):
        self.busy_night()
        self.assert_clean(overnight.plan_for(self.st, NOW, env=self.env, home=self.root))
        self.assert_clean(overnight.landed_for(self.st, NOW, env=self.env, home=self.root))
        out = self.tool()
        self.assert_clean(out["label"]["label"])
        self.assert_clean(json.dumps(out["value"]).replace("1", "").replace("2", ""))  # counts only, no names


if __name__ == "__main__":
    unittest.main()
