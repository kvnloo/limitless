"""ui_card: the state card and the week review as one small self-contained HTML card (synthetic lines only)."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import ui_card  # noqa: E402

LINES = ["window: peak (proxy)",
         "sleep short (proxy); readiness unknown (no digest in the last day)",
         "habit this week: walk after lunch; today Done",
         "asks waiting on you",
         "focused mode: answer briefly, hold non-urgent asks"]


def body(html):
    """The words a person reads: the text of the card's <body>, tags left out."""
    return re.sub(r"<[^>]*>", "", re.search(r"(?s)<body>(.*)</body>", html).group(1))


class Render(unittest.TestCase):
    def test_one_self_contained_html_string(self):
        r = ui_card.render("Today", LINES, "state")
        html = r["html"]
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("<style>", html)
        self.assertNotRegex(html.lower(), r"<script|<link|@import|url\(|https?:|src=|@font-face|javascript:")
        self.assertNotRegex(html.lower(), r"\bon[a-z]+\s*=")   # no inline event handlers either

    def test_each_line_is_one_row_with_a_chip(self):
        r = ui_card.render("Today", LINES, "state")
        self.assertEqual(r["rows"], len(LINES))
        self.assertEqual(r["dropped"], 0)
        self.assertEqual(r["html"].count('class="row '), len(LINES))
        self.assertEqual([c for _, c in r["chips"]], ["known", "unknown", "known", "held", "held"])

    def test_chip_comes_from_the_line_words(self):
        self.assertEqual(ui_card.chip("window: unknown"), "unknown")
        self.assertEqual(ui_card.chip("not recording: scale"), "unknown")
        self.assertEqual(ui_card.chip("quiet tonight: pushes held"), "held")
        self.assertEqual(ui_card.chip("asks waiting on you"), "held")
        self.assertEqual(ui_card.chip("sleep short (proxy)"), "known")
        self.assertEqual(ui_card.chip("sleep long; flow unknown"), "unknown")   # unknown wins over known

    def test_a_line_that_fails_the_gate_is_dropped_and_counted(self):
        r = ui_card.render("Week", ["walk: 3 of 5 logged days this week.", "rides this week: one"], "week")
        self.assertEqual((r["rows"], r["dropped"]), (1, 1))
        self.assertNotRegex(body(r["html"]), r"\d")

    def test_every_line_goes_through_tier_audit_gate(self):
        seen = []
        orig = ui_card.tier_audit.gate

        def spy(hook, text, opt_in, **kw):
            seen.append((hook, text, opt_in))
            return orig(hook, text, opt_in, **kw)
        ui_card.tier_audit.gate = spy
        try:
            ui_card.render("Today", ["a", "b 7"], "state", env={})
        finally:
            ui_card.tier_audit.gate = orig
        self.assertEqual(seen, [("ui_card:state", "a", False), ("ui_card:state", "b 7", False)])

    def test_text_is_escaped(self):
        r = ui_card.render("<b>Title</b>", ["<script>alert('x')</script> & more"], "state")
        self.assertNotIn("<script>", r["html"])
        self.assertNotIn("<b>Title", r["html"])
        self.assertIn("&lt;script&gt;", r["html"])
        self.assertIn("&amp; more", r["html"])

    def test_no_digit_outside_the_style_block(self):
        r = ui_card.render("Today", LINES, "state")
        self.assertNotRegex(body(r["html"]), r"\d")

    def test_blank_and_non_string_lines_are_dropped(self):
        r = ui_card.render("Today", ["", "   ", None, 5, "window: peak"], "state")
        self.assertEqual((r["rows"], r["dropped"]), (1, 4))

    def test_a_digit_title_falls_back_to_the_kind(self):
        r = ui_card.render("Week 7", ["a"], "week")
        self.assertNotRegex(body(r["html"]), r"\d")
        self.assertIn(ui_card.TITLES["week"], r["html"])

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            ui_card.render("x", ["a"], "other")


if __name__ == "__main__":
    unittest.main()
