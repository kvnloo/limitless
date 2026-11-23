"""palace config: ``palace_link`` (a deep link or URL; unset by default) and ``palace_label`` (default "memory
palace"). Unset, or a link that may not ride in a line the person reads, is off with one plain-words reason.
Synthetic links only."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import palace  # noqa: E402
from limitless.decision_window import WindowState  # noqa: E402

LINK = "palace://example"


class Link(unittest.TestCase):
    def test_unset_by_default(self):
        for cfg in ({}, None, {"palace_link": None}, {"palace_link": ""}, {"palace_link": "   "}, "palace://example"):
            self.assertIsNone(palace.link(cfg), cfg)

    def test_a_deep_link_or_url_is_kept(self):
        for v in (LINK, "https://example.org/walk", "  palace://example  "):
            self.assertEqual(palace.link({"palace_link": v}), v.strip())

    def test_a_link_that_cannot_ride_in_a_digit_free_line_is_off(self):
        for v in ("palace://room-7", "not a link", "palace://a b", 42, True, ["palace://example"],
                  "palace://" + "a" * 500):
            self.assertIsNone(palace.link({"palace_link": v}), v)


class Label(unittest.TestCase):
    def test_default_label(self):
        self.assertEqual(palace.DEFAULT_LABEL, "memory palace")
        for cfg in ({}, None, {"palace_label": ""}, {"palace_label": 3}, {"palace_label": "room 7"},
                    {"palace_label": "x" * 200}, {"palace_label": "a\nb"}):
            self.assertEqual(palace.label(cfg), "memory palace", cfg)

    def test_own_label(self):
        self.assertEqual(palace.label({"palace_label": " mind palace "}), "mind palace")


class Off(unittest.TestCase):
    def test_unset_is_off_with_one_plain_reason_whatever_the_window(self):
        for win in (WindowState("trough"), WindowState("peak"), None):
            word, why = palace.status({"window": win, "muted": False, "anki_offered": False,
                                       "offered_today": False}, {})
            self.assertEqual((word, why), ("off", "no memory palace link set"))
            self.assertIsNone(palace.offer({"window": win, "muted": False, "anki_offered": False,
                                            "offered_today": False}, {}))
        self.assertEqual(palace.NO_LINK, "no memory palace link set")


if __name__ == "__main__":
    unittest.main()
