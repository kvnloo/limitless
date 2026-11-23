"""message_shape keeps the app-lists ask whole: a long wake brief folds its middle lines, never the pre-filled
"work apps: / feed apps:" reply at its end or the line that introduces it, and never cuts them. Synthetic text.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import apps_ask, apps_reply, message_shape  # noqa: E402

ASK = [apps_ask.PROMPT, "work apps: alacritty, code", "feed apps: instagram, reddit"]
WHY = "Why now: you just woke up"
BRIEF = ["State: synthetic"] + [f"Line {w}" for w in ("one", "two", "three", "four", "five")]


class Shape(unittest.TestCase):
    def test_a_long_brief_folds_the_middle_and_keeps_the_ask(self):
        text, folded, _ = message_shape.fit("Wake-up brief", "\n".join(BRIEF + ASK + [WHY]))
        lines = text.splitlines()
        self.assertGreater(folded, 0)
        self.assertEqual(lines[0], BRIEF[0])
        self.assertEqual(lines[-4:], ASK + [WHY])
        self.assertEqual(apps_reply.parse("\n".join(lines[-3:-1])),
                         {apps_reply.WORK: ("alacritty", "code"), apps_reply.FEED: ("instagram", "reddit")})

    def test_the_default_limit_holds_with_the_ask(self):
        text = message_shape.shape("Wake-up brief", "\n".join(BRIEF + ASK + [WHY]))
        self.assertEqual(len(text.splitlines()), message_shape.DEFAULT_MAX_LINES)

    def test_a_long_reply_line_is_never_cut(self):
        long = "feed apps: " + ", ".join(f"synthetic-feed-app-{w}" for w in "abcdefghijklmnopqrst")
        self.assertGreater(len(long), message_shape.DEFAULT_MAX_LINE_CHARS)
        body = "\n".join(["State: synthetic", apps_ask.PROMPT, "work apps: code", long, WHY])
        self.assertIn(long, message_shape.shape("Wake-up brief", body).splitlines())

    def test_a_short_brief_with_the_ask_comes_back_byte_for_byte(self):
        body = "\n".join(["State: synthetic"] + ASK + [WHY])
        self.assertEqual(message_shape.fit("Wake-up brief", body), (body, 0, 0))

    def test_reply_lines_in_the_middle_are_folded_as_before(self):
        body = "\n".join(["State: synthetic", "work apps: code"] + BRIEF[1:] + ["Reply: Yes / No / Later", WHY])
        lines = message_shape.shape("x", body).splitlines()
        self.assertEqual(lines[-2:], ["Reply: Yes / No / Later", WHY])
        self.assertEqual(len(lines), message_shape.DEFAULT_MAX_LINES)


if __name__ == "__main__":
    unittest.main()
