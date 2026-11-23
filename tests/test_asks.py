"""asks: every needs-the-person ask carries a window class; at most one decision per peak window."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import asks  # noqa: E402
from limitless.decision_window import WindowState  # noqa: E402

PEAK = WindowState(cls="peak", since="wake", source="events")
TROUGH = WindowState(cls="trough", since="wake", source="events")
FOCUS = WindowState(cls="peak", since="focus_start", source="glide", hold_asks=True)
UNKNOWN = WindowState(cls="unknown", source="chain", confidence=0.0)


def ask(i, kind, at, **kw):
    return dict({"id": i, "kind": kind, "title": f"ask {i}", "at": at}, **kw)


QUEUE = [ask("b", "decision", 200), ask("a", "decision", 100), ask("c", "approval", 300, effort="deep"),
         ask("d", "approval", 400, effort="light"), ask("e", "fyi", 500), ask("f", "mystery", 600)]


def actions(rows):
    return {i: a for i, a, _ in rows}


class Classify(unittest.TestCase):
    def test_decisions_and_deep_approvals_are_peak(self):
        self.assertEqual(asks.classify({"kind": "decision"}), "peak")
        self.assertEqual(asks.classify({"kind": "decision", "effort": "light"}), "peak")
        self.assertEqual(asks.classify({"kind": "approval", "effort": "deep"}), "peak")

    def test_light_approvals_are_anytime(self):
        self.assertEqual(asks.classify({"kind": "approval", "effort": "light"}), "anytime")
        self.assertEqual(asks.classify({"kind": "approval"}), "anytime")

    def test_fyi_is_trough(self):
        self.assertEqual(asks.classify({"kind": "fyi"}), "trough")
        self.assertEqual(asks.classify({"kind": "fyi", "effort": "deep"}), "trough")

    def test_unknown_kind_is_anytime_never_dropped(self):
        for ask in ({"kind": "poll"}, {}, {"kind": None}, {"kind": 3}, "not a dict", None):
            self.assertEqual(asks.classify(ask), "anytime", ask)

    def test_case_and_space_in_the_fields_do_not_matter(self):
        self.assertEqual(asks.classify({"kind": " Decision "}), "peak")
        self.assertEqual(asks.classify({"kind": "APPROVAL", "effort": "Deep"}), "peak")

    def test_never_reads_the_clock(self):
        same = {"kind": "approval", "effort": "deep", "at": "2026-01-05T03:00:00Z"}
        other = dict(same, at="2026-01-05T21:00:00Z")
        self.assertEqual(asks.classify(same), asks.classify(other))


class Plan(unittest.TestCase):
    def test_peak_window_delivers_the_oldest_peak_ask_only(self):
        rows = asks.plan(QUEUE, PEAK, 0)
        self.assertEqual(actions(rows), {"a": "deliver", "b": "hold", "c": "hold", "d": "deliver",
                                         "e": "fold", "f": "deliver"})

    def test_rows_are_triples_for_every_ask_none_dropped(self):
        rows = asks.plan(QUEUE, PEAK, 0)
        self.assertEqual(len(rows), len(QUEUE))
        for r in rows:
            self.assertEqual(len(r), 3)
            self.assertIn(r[1], ("deliver", "hold", "fold"))
            self.assertTrue(isinstance(r[2], str) and r[2])

    def test_held_peak_asks_say_why_in_plain_words(self):
        reason = dict((i, why) for i, _, why in asks.plan(QUEUE, PEAK, 0))
        self.assertIn("one decision per peak window", reason["b"])
        self.assertIn("next peak window", reason["b"])
        self.assertIn("send gate", reason["d"])
        self.assertIn("brief", reason["e"])

    def test_a_decision_already_sent_this_window_holds_every_peak_ask(self):
        self.assertEqual(actions(asks.plan(QUEUE, PEAK, 1)),
                         {"a": "hold", "b": "hold", "c": "hold", "d": "deliver", "e": "fold", "f": "deliver"})

    def test_outside_a_peak_window_peak_asks_hold(self):
        for state in (TROUGH, UNKNOWN, None):
            got = actions(asks.plan(QUEUE, state, 0))
            self.assertEqual((got["a"], got["b"], got["c"]), ("hold", "hold", "hold"), state)
            self.assertEqual((got["d"], got["e"]), ("deliver", "fold"), state)

    def test_focus_block_holds_everything_but_urgent(self):
        q = QUEUE + [ask("u", "fyi", 50, urgent=True)]
        got = actions(asks.plan(q, FOCUS, 0))
        self.assertEqual(got.pop("u"), "deliver")
        self.assertEqual(set(got.values()), {"hold"})
        why = dict((i, w) for i, _, w in asks.plan(q, FOCUS, 0))
        self.assertIn("focus block", why["e"])

    def test_urgent_never_counts_against_the_one_per_window_limit(self):
        q = [ask("u", "decision", 10, urgent=True), ask("v", "decision", 20, urgent=True), ask("a", "decision", 30)]
        self.assertEqual(actions(asks.plan(q, PEAK, 0)), {"u": "deliver", "v": "deliver", "a": "deliver"})
        self.assertEqual(actions(asks.plan(q, PEAK, 1)), {"u": "deliver", "v": "deliver", "a": "hold"})
        self.assertEqual(actions(asks.plan(q, TROUGH, 0)), {"u": "deliver", "v": "deliver", "a": "hold"})

    def test_urgent_must_be_true_not_truthy(self):
        q = [ask("x", "fyi", 1, urgent="yes")]
        self.assertEqual(actions(asks.plan(q, FOCUS, 0)), {"x": "hold"})

    def test_asleep_holds_but_fyi_still_folds_into_the_brief(self):
        asleep = {"value": "asleep", "modality": "proxy", "age_h": 0.0, "evidence_tier": "indirect"}
        got = actions(asks.plan(QUEUE, asleep, 0))
        self.assertEqual(got, {"a": "hold", "b": "hold", "c": "hold", "d": "hold", "e": "fold", "f": "hold"})

    def test_a_window_envelope_works_like_a_window_state(self):
        env = {"value": "peak", "modality": "proxy", "age_h": 0.1, "evidence_tier": "indirect"}
        self.assertEqual(asks.plan(QUEUE, env, 0), asks.plan(QUEUE, PEAK, 0))

    def test_oldest_first_by_its_at_time_iso_or_epoch_and_undated_last(self):
        q = [ask("late", "decision", "2026-01-05T09:00:00Z"), ask("early", "decision", "2026-01-05T08:00:00Z")]
        self.assertEqual(actions(asks.plan(q, PEAK, 0))["early"], "deliver")
        q = [ask("nodate", "decision", None), ask("dated", "decision", 5)]
        self.assertEqual(actions(asks.plan(q, PEAK, 0))["dated"], "deliver")

    def test_plan_keeps_the_queue_order_in_its_output(self):
        self.assertEqual([r[0] for r in asks.plan(QUEUE, PEAK, 0)], [a["id"] for a in QUEUE])

    def test_empty_queue_is_an_empty_plan(self):
        self.assertEqual(asks.plan([], PEAK, 0), [])
        self.assertEqual(asks.plan(None, PEAK, 0), [])


class Queue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.q = self.dir / "asks.jsonl"
        self.q.write_text("".join(json.dumps(a) + "\n" for a in QUEUE))

    def env(self, **kw):
        return dict({"LIMITLESS_CONFIG": str(self.dir / "no-config.json")}, **kw)

    def test_path_from_env_then_config(self):
        self.assertEqual(asks.queue_path(self.env(LIMITLESS_ASKS=str(self.q))), str(self.q))
        cfg = self.dir / "config.json"
        cfg.write_text(json.dumps({"asks_path": str(self.q)}))
        self.assertEqual(asks.queue_path({"LIMITLESS_CONFIG": str(cfg)}), str(self.q))
        self.assertEqual(asks.queue_path({"LIMITLESS_CONFIG": str(cfg), "LIMITLESS_ASKS": "other.jsonl"}),
                         "other.jsonl")
        self.assertIsNone(asks.queue_path(self.env()))
        cfg.write_text(json.dumps({"asks_path": 7}))
        self.assertIsNone(asks.queue_path({"LIMITLESS_CONFIG": str(cfg)}))

    def test_reads_the_queue_and_plans_it(self):
        got = asks.plan_queue(PEAK, 0, self.env(LIMITLESS_ASKS=str(self.q)))
        self.assertEqual(got, asks.plan(QUEUE, PEAK, 0))

    def test_missing_or_broken_file_is_an_empty_plan(self):
        bad = self.dir / "bad.jsonl"
        for content in (None, b"", b"not json at all\n", b"\xff\xfe\x00garbage", b"[1, 2]\n\"str\"\n"):
            if content is None:
                path = str(self.dir / "absent.jsonl")
            else:
                bad.write_bytes(content)
                path = str(bad)
            self.assertEqual(asks.plan_queue(PEAK, 0, self.env(LIMITLESS_ASKS=path)), [], content)
        self.assertEqual(asks.plan_queue(PEAK, 0, self.env(LIMITLESS_ASKS=str(self.dir))), [])
        self.assertEqual(asks.plan_queue(PEAK, 0, self.env()), [])

    def test_bad_lines_are_skipped_good_ones_kept(self):
        self.q.write_text(json.dumps(QUEUE[1]) + "\n{oops\n" + json.dumps(QUEUE[3]) + "\n")
        got = asks.plan_queue(PEAK, 0, self.env(LIMITLESS_ASKS=str(self.q)))
        self.assertEqual([(i, a) for i, a, _ in got], [("a", "deliver"), ("d", "deliver")])

    def test_delivered_rows_are_not_planned_again(self):
        rows = [ask("a", "decision", 100, delivered_at=150), ask("b", "decision", 200)]
        self.assertEqual([r["id"] for r in asks.pending(rows)], ["b"])

    def test_read_only_the_queue_bytes_never_change(self):
        before, mtime = self.q.read_bytes(), self.q.stat().st_mtime_ns
        for state in (PEAK, FOCUS, TROUGH, None):
            asks.plan_queue(state, 0, self.env(LIMITLESS_ASKS=str(self.q)))
        self.assertEqual(self.q.read_bytes(), before)
        self.assertEqual(self.q.stat().st_mtime_ns, mtime)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["asks.jsonl"])

    def test_reasons_are_plain_words_without_card_ids(self):
        q = [ask("t_510c250d", "decision", 1, title="t_510c250d: pick the plan for the week"),
             ask("t_0a1b2c3d", "decision", 2, title="approve t_0a1b2c3d the draft"),
             ask("t_99887766", "fyi", 3, title="t_99887766 build finished")]
        for state in (PEAK, FOCUS, TROUGH):
            for _, _, why in asks.plan(q, state, 0):
                self.assertNotRegex(why, r"\bt_[0-9a-f]{6,12}\b", why)
        why = [w for _, _, w in asks.plan(q, PEAK, 0)]
        self.assertTrue(why[0].startswith("pick the plan for the week: "), why[0])
        self.assertTrue(why[1].startswith("approve the draft: "), why[1])

    def test_reason_reuses_the_send_gate_scrub(self):
        from limitless import send_gate
        self.assertIs(asks.scrub, send_gate.scrub)


if __name__ == "__main__":
    unittest.main()
