"""asks: every needs-the-person ask carries a window class; at most one decision per peak window."""
import os
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
