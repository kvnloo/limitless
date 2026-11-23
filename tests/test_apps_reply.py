"""Apps replies: "work apps: A, B" / "feed apps: C, D" read from one whole message.

Synthetic app names only; nothing sends.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import apps_reply  # noqa: E402

W, F = apps_reply.WORK, apps_reply.FEED


class Parse(unittest.TestCase):
    def test_work_apps_comma_list(self):
        self.assertEqual(apps_reply.parse("work apps: Editor, Terminal, Notes"), {W: ("Editor", "Terminal", "Notes")})

    def test_feed_apps_comma_list(self):
        self.assertEqual(apps_reply.parse("feed apps: scrollerapp, clipapp"), {F: ("scrollerapp", "clipapp")})

    def test_prefix_is_case_insensitive_and_spacing_is_loose(self):
        self.assertEqual(apps_reply.parse("  WORK  Apps :editor"), {W: ("editor",)})
        self.assertEqual(apps_reply.parse("Feed apps:  a "), {F: ("a",)})

    def test_newline_separated_names(self):
        self.assertEqual(apps_reply.parse("work apps:\neditor\nterminal\n\n notes "),
                         {W: ("editor", "terminal", "notes")})

    def test_names_are_trimmed_and_deduplicated_case_insensitively(self):
        self.assertEqual(apps_reply.parse("work apps: editor , Editor,,terminal, editor"),
                         {W: ("editor", "terminal")})

    def test_both_lines_in_one_message_are_both_read(self):
        self.assertEqual(apps_reply.parse("work apps: editor, terminal\nfeed apps: scrollerapp"),
                         {W: ("editor", "terminal"), F: ("scrollerapp",)})

    def test_none_clears(self):
        self.assertEqual(apps_reply.parse("work apps: none"), {W: ()})
        self.assertEqual(apps_reply.parse("Feed Apps: NONE"), {F: ()})

    def test_twenty_names_is_the_most(self):
        names = [f"app{i}" for i in range(20)]
        self.assertEqual(apps_reply.parse("work apps: " + ", ".join(names)), {W: tuple(names)})
        self.assertIsNone(apps_reply.parse("work apps: " + ", ".join(names + ["one-more"])))

    def test_sixty_characters_is_the_longest_name(self):
        self.assertEqual(apps_reply.parse("feed apps: " + "a" * 60), {F: ("a" * 60,)})
        self.assertIsNone(apps_reply.parse("feed apps: ok, " + "a" * 61))

    def test_anything_else_changes_nothing(self):
        for text in ("thanks", "my work apps: editor", "work apps", "work apps:", "work apps: , ,",
                     "work app: editor", "feeds: x", "apps: editor", "hello\nwork apps: editor",
                     "work apps: editor\nwork apps: terminal", "", "   ", None, 5):
            self.assertIsNone(apps_reply.parse(text), text)

    def test_none_only_clears_alone(self):
        self.assertEqual(apps_reply.parse("work apps: none, editor"), {W: ("none", "editor")})


if __name__ == "__main__":
    unittest.main()
