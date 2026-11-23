"""limitless/held.py: a message held by Sleep mode is kept once in held.jsonl, not once per retry.

Synthetic messages only; nothing is sent.
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import held  # noqa: E402

KEY = "wake_brief:1999990000"


class HeldAdd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "held.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, at, title, body, once=None, tag="limitless"):
        held.add(self.path, {"at": at, "tag": tag, "title": title, "body": body}, once)

    def lines(self):
        return [json.loads(x) for x in self.path.read_text().splitlines()]

    def test_same_once_key_twice_keeps_one_row_with_the_newest_text(self):
        self.add(100, "Wake-up brief", "first wording", KEY)
        self.add(200, "Wake-up brief", "fresher wording", KEY)
        rows = self.lines()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["at"], rows[0]["body"], rows[0]["once"]), (200, "fresher wording", KEY))

    def test_same_title_and_body_without_a_key_keeps_one_row(self):
        for at in (100, 200, 300, 400):
            self.add(at, "Wake-up brief", "the brief")
        rows = self.lines()
        self.assertEqual([r["at"] for r in rows], [400])
        self.assertNotIn("once", rows[0])

    def test_two_different_messages_keep_two_rows(self):
        self.add(100, "Pick one", "keep the loop")
        self.add(200, "Pick two", "keep the loop")
        self.add(300, "Pick one", "a different body")
        self.assertEqual([(r["title"], r["body"]) for r in self.lines()],
                         [("Pick one", "keep the loop"), ("Pick two", "keep the loop"),
                          ("Pick one", "a different body")])

    def test_different_once_keys_are_different_messages(self):
        self.add(100, "Wake-up brief", "the brief", "wake_brief:1")
        self.add(200, "Wake-up brief", "the brief", "wake_brief:2")
        self.assertEqual(len(self.lines()), 2)

    def test_a_why_line_only_difference_keeps_one_row(self):
        self.add(100, "Pick one", "keep the loop\nWhy now: you woke up")
        self.add(200, "Pick one", "keep the loop\nWhy now: your focus is high right now")
        self.add(300, "Pick one", "keep the loop")
        rows = self.lines()
        self.assertEqual([(r["at"], r["body"]) for r in rows], [(300, "keep the loop")])

    def test_card_ids_do_not_change_the_message(self):
        self.add(100, "Pick one", "Decision: t_510c250d: keep the loop")
        self.add(200, "Pick one", "Decision: keep the loop")
        self.assertEqual(len(self.lines()), 1)

    def test_order_is_by_the_newest_hold_time(self):
        self.add(100, "A", "a")
        self.add(200, "B", "b")
        self.add(300, "A", "a again", None)
        self.add(300, "A", "a")      # same as the first A: moves after B
        self.assertEqual([(r["title"], r["body"], r["at"]) for r in self.lines()],
                         [("B", "b", 200), ("A", "a again", 300), ("A", "a", 300)])

    def test_the_file_is_private_and_replaced_whole(self):
        self.add(100, "A", "a")
        self.add(200, "A", "a")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir() if p.name != held.LOCK_NAME),
                         ["held.jsonl"], "no temp file is left behind")

    def test_a_corrupt_line_is_kept_as_it_is_and_nothing_raises(self):
        self.path.write_text('{"at": 50, "title": "Old", "body": "old"}\n{nope\n[1, 2]\n')
        self.add(100, "A", "a")
        self.add(200, "A", "a")
        text = self.path.read_text().splitlines()
        self.assertIn("{nope", text)
        self.assertIn("[1, 2]", text)
        self.assertEqual([r["title"] for r in held.rows(self.path)], ["Old", "A"])

    def test_older_rows_from_before_the_key_are_collapsed_on_the_next_hold(self):
        self.path.write_text("".join(json.dumps({"at": at, "tag": "limitless", "title": "Wake-up brief",
                                                 "body": "the brief"}) + "\n" for at in (10, 20, 30)))
        self.add(40, "Wake-up brief", "the brief")
        self.assertEqual([r["at"] for r in self.lines()], [40])


class HeldRows(unittest.TestCase):
    """The reader lists each held message once, also from a file an older kevin-push wrote with repeats."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "held.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rows, extra=""):
        self.path.write_text("".join(json.dumps(r) + "\n" for r in rows) + extra)

    def test_duplicates_from_an_older_version_are_listed_once(self):
        self.write([{"at": 10, "tag": "limitless", "title": "Wake-up brief", "body": "the brief"},
                    {"at": 20, "tag": "x", "title": "Pick one", "body": "keep the loop"},
                    {"at": 30, "tag": "limitless", "title": "Wake-up brief", "body": "the brief"},
                    {"at": 40, "tag": "limitless", "title": "Wake-up brief", "body": "the brief"},
                    {"at": 50, "tag": "limitless", "title": "Wake-up brief", "body": "the brief"}])
        self.assertEqual([(r["title"], r["at"]) for r in held.rows(self.path)],
                         [("Pick one", 20), ("Wake-up brief", 50)])

    def test_rows_with_one_once_key_are_listed_once_newest_text(self):
        self.write([{"at": 10, "title": "Wake-up brief", "body": "early", "once": KEY},
                    {"at": 20, "title": "Wake-up brief", "body": "late", "once": KEY}])
        self.assertEqual([r["body"] for r in held.rows(self.path)], ["late"])

    def test_a_corrupt_line_is_skipped_without_a_traceback(self):
        self.write([{"at": 10, "title": "A", "body": "a"}], extra='{nope\n"text"\n{"at": "x"}\n\n')
        self.assertEqual([r["title"] for r in held.rows(self.path)], ["A"])

    def test_missing_or_unreadable_file_is_nothing_held(self):
        self.assertEqual(held.rows(self.path), [])
        self.path.mkdir()
        self.assertEqual(held.rows(self.path), [])

    def test_rows_is_read_only(self):
        self.write([{"at": 10, "title": "A", "body": "a"}, {"at": 20, "title": "A", "body": "a"}])
        before = self.path.read_text()
        held.rows(self.path)
        self.assertEqual(self.path.read_text(), before)


if __name__ == "__main__":
    unittest.main()
