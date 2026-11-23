"""palace.offer: one optional line, "A short memory palace walk fits now." and the link, only in a trough when
the person is awake, not in a focus block or focused mode, not muted, had no Anki offer in this trough and had
no palace offer yet this wake day. Peak, unknown or any other state: None. Pure: synthetic inputs, no clock."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import modes, palace  # noqa: E402
from limitless.decision_window import WindowState  # noqa: E402
from limitless.envelope import envelope  # noqa: E402

CFG = {"palace_link": "palace://example"}
LINE = "A short memory palace walk fits now. palace://example"


def st(window=WindowState("trough", since="wake"), **kw):
    out = {"window": window, "muted": False, "anki_offered": False, "offered_today": False}
    out.update(kw)
    return out


class Fits(unittest.TestCase):
    def test_trough_offers_the_one_line_with_the_link(self):
        for w in (WindowState("trough", since="wake"), envelope("trough", "proxy", 0.1), {"cls": "trough"}):
            self.assertEqual(palace.offer(st(w), CFG), LINE, w)
            self.assertEqual(palace.status(st(w), CFG), ("fits now", None))
        self.assertFalse(any(c.isdigit() for c in LINE))

    def test_own_label_rides_in_the_line(self):
        cfg = dict(CFG, palace_label="mind palace")
        self.assertEqual(palace.offer(st(), cfg), "A short mind palace walk fits now. palace://example")


class NotNow(unittest.TestCase):
    def assertNot(self, state, why_has):
        self.assertIsNone(palace.offer(state, CFG))
        word, why = palace.status(state, CFG)
        self.assertEqual(word, "not now")
        self.assertIn(why_has, why)
        self.assertFalse(any(c.isdigit() for c in why), why)

    def test_never_outside_a_trough(self):
        for w in (WindowState("peak"), envelope("peak", "proxy", 0.1), WindowState("anytime"),
                  WindowState("wind_down")):
            self.assertNot(st(w), "so this waits for a lighter moment")

    def test_unknown_never_offers(self):
        for w in (WindowState("unknown"), envelope("unknown", "proxy", 0.1), None, WindowState("trough", confidence=0.2),
                  "trough", 42, {"cls": None}):
            self.assertNot(st(w), "not clear yet")

    def test_never_asleep(self):
        for w in (envelope("asleep", "proxy", 0.1), {"cls": "asleep"}):
            self.assertNot(st(w), "asleep")

    def test_never_in_a_focus_block_or_focused_mode(self):
        self.assertNot(st(WindowState("trough", hold_asks=True)), "focus block")
        self.assertNot(st(modes.apply(WindowState("trough"), modes.FOCUSED)), "focus block")

    def test_never_muted_and_unknown_quiet_counts_as_muted(self):
        for m in (True, None, "no", 0):
            self.assertNot(st(muted=m), "muted")

    def test_one_learning_offer_per_trough(self):
        for a in (True, None, 1):
            self.assertNot(st(anki_offered=a), "Anki")

    def test_at_most_once_per_wake_day_and_unknown_counts_as_offered(self):
        for t in (True, None, 0):
            self.assertNot(st(offered_today=t), "since you woke")

    def test_not_a_dict_is_unknown(self):
        for s in (None, "trough", [], 1):
            self.assertIsNone(palace.offer(s, CFG))
            self.assertEqual(palace.status(s, CFG)[0], "not now")

    def test_off_wins_over_every_other_reason(self):
        self.assertEqual(palace.status(st(WindowState("peak"), muted=True), {}), ("off", palace.NO_LINK))


class Words(unittest.TestCase):
    def test_words_reads_off_fits_now_or_not_now_with_the_reason(self):
        self.assertEqual(palace.words(st(), {}), "off")
        self.assertEqual(palace.words(st(), CFG), "fits now")
        w = palace.words(st(muted=True), CFG)
        self.assertTrue(w.startswith("not now: "), w)
        self.assertFalse(any(c.isdigit() for c in w))


if __name__ == "__main__":
    unittest.main()
