"""Send gate tests. Synthetic fixtures only (no Kevin data)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import send_gate as g  # noqa: E402


class ScrubCardIds(unittest.TestCase):
    def test_removes_prefixed_card_id(self):
        self.assertEqual(g.scrub("Decision: t_510c250d: factory loop"), "Decision: factory loop")

    def test_removes_inline_card_id(self):
        self.assertEqual(g.scrub("Sampler card t_c936a962 is built"), "Sampler card is built")

    def test_keeps_ordinary_words(self):
        self.assertEqual(g.scrub("start_time t_x and test_abc"), "start_time t_x and test_abc")


NOW = 2_000_000_000.0


def decide(tag="x", title="T", body="b", cls="decision", sent=(), asleep=False):
    return g.decide(tag, title, body, cls, NOW, list(sent), asleep)


class Decide(unittest.TestCase):
    def test_asks_digest_is_folded_into_the_brief_not_sent(self):
        self.assertEqual(decide(tag="asks", title="Asks waiting on you"), "fold")

    def test_asks_digest_folds_even_when_cap_has_room(self):
        self.assertEqual(decide(tag="asks", title="Asks waiting on you", cls="critical"), "fold")

    def test_report_class_is_log_only(self):
        self.assertEqual(decide(cls="report"), "log")

    def test_decision_is_sent(self):
        self.assertEqual(decide(), "send")

    def test_wake_brief_is_sent_whatever_the_class(self):
        self.assertEqual(decide(tag="limitless", title="Wake-up brief", cls="digest"), "send")

    def test_miq_prompt_is_sent_although_its_class_is_report(self):
        # The wind-down MIQ prompt was logged, never delivered, while it used the default class.
        self.assertEqual(decide(tag="limitless", title="MIQ for tonight?", cls="report"), "send")

    def test_miq_prompt_is_held_in_sleep_mode(self):
        self.assertEqual(decide(tag="limitless", title="MIQ for tonight?", cls="report", asleep=True), "hold")

    def test_same_text_within_12h_is_duplicate(self):
        k = g.key("T", "b")
        self.assertEqual(decide(sent=[{"t": NOW - 3600, "k": k}]), "duplicate")

    def test_duplicate_ignores_card_ids(self):
        k = g.key("T", "fix it")
        self.assertEqual(decide(body="fix it t_0123abcd", sent=[{"t": NOW - 60, "k": k}]), "duplicate")

    def test_same_text_after_12h_is_sent(self):
        k = g.key("T", "b")
        self.assertEqual(decide(sent=[{"t": NOW - 13 * 3600, "k": k}]), "send")

    def test_daily_cap(self):
        sent = [{"t": NOW - i, "k": str(i)} for i in range(g.DAILY_CAP)]
        self.assertEqual(decide(sent=sent), "cap")

    def test_sleep_mode_holds_non_critical(self):
        self.assertEqual(decide(asleep=True), "hold")

    def test_sleep_mode_never_holds_critical(self):
        self.assertEqual(decide(cls="critical", asleep=True), "send")

    def test_back_from_nap_is_never_held(self):
        self.assertEqual(decide(tag="limitless", title="Back from nap", asleep=True), "send")


if __name__ == "__main__":
    unittest.main()
