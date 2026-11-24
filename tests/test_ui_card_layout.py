"""ui_card layout: at most eight rows, a phone-width layout, large calm type, CSS-only motion (synthetic lines)."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import ui_card  # noqa: E402

PHONE_PX = 360          # the narrowest common phone screen, in CSS pixels
REM_PX = 16


def css(html):
    return re.search(r"(?s)<style>(.*?)</style>", html).group(1)


def px(value, unit):
    return float(value) * (REM_PX if unit in ("rem", "em") else 1)


class Layout(unittest.TestCase):
    def setUp(self):
        self.html = ui_card.render("Today", ["window: peak (proxy)", "sleep short (proxy)"], "state")["html"]
        self.css = css(self.html)

    def test_at_most_eight_rows(self):
        lines = [f"line {w}" for w in ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
                                         "ten")]
        r = ui_card.render("Today", lines, "state")
        self.assertEqual(ui_card.MAX_ROWS, 8)
        self.assertEqual((r["rows"], r["dropped"]), (8, 2))
        self.assertEqual(r["html"].count('class="row '), 8)
        self.assertNotIn("line nine", r["html"])

    def test_viewport_is_the_device_width(self):
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1">', self.html)

    def test_no_fixed_width_over_a_phone_screen(self):
        for prop, value, unit in re.findall(r"(?<![-\w])((?:min-)?width)\s*:\s*([\d.]+)(px|rem|em|vw|ch|pt)",
                                            self.css):
            if unit == "vw":
                self.assertLessEqual(float(value), 100, prop)
            else:
                self.assertLessEqual(px(value, unit), PHONE_PX, f"{prop}:{value}{unit}")

    def test_no_horizontal_scroll_rule(self):
        self.assertNotRegex(self.css, r"overflow(-x)?\s*:\s*(scroll|auto)")
        self.assertNotRegex(self.css, r"white-space\s*:\s*(nowrap|pre)\b")
        self.assertIn("overflow-wrap:anywhere", self.css)

    def test_large_type(self):
        size = re.search(r"body\{[^}]*font:([\d.]+)rem", self.css)
        self.assertIsNotNone(size)
        self.assertGreaterEqual(float(size.group(1)), 1.125)

    def test_muted_palette_has_no_saturated_colour(self):
        for hexc in re.findall(r"#([0-9a-fA-F]{6})\b", self.css):
            r, g, b = (int(hexc[i:i + 2], 16) for i in (0, 2, 4))
            spread = max(r, g, b) - min(r, g, b)
            self.assertLessEqual(spread, 90, f"#{hexc} is too saturated for a calm card")

    def test_motion_is_css_only_and_respects_reduced_motion(self):
        self.assertIn("@keyframes", self.css)
        self.assertRegex(self.css, r"@media \(prefers-reduced-motion:reduce\)\{\*\{animation:none")
        self.assertNotRegex(self.html.lower(), r"<script|javascript:|\bon[a-z]+\s*=")

    def test_chip_colours_exist_for_each_state(self):
        for c in ui_card.CHIPS:
            self.assertIn(f".{c} .chip{{", self.css)


if __name__ == "__main__":
    unittest.main()
