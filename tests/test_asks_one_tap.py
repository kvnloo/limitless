"""asks.render / asks.reply: each ask the person sees ends in its one-tap choices line; Later keeps it waiting.

Synthetic asks only; nothing sends and the queue file is never written.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import asks, one_tap  # noqa: E402

ASK = {"id": "a1", "kind": "decision", "title": "Pick the synthetic plan for t_510c250d", "at": 1}


class Choices(unittest.TestCase):
    def test_default_yes_no_later(self):
        self.assertEqual(asks.answers(ASK), ("Yes", "No", "Later"))
        for bad in ({}, None, "x", {"answers": []}, {"answers": ["Ok"]}, {"answers": ["Ok", "Not now"]},
                    {"answers": ["A1", "B"]}, {"answers": "Yes"}, {"answers": ["a", "b", "c", "d", "e"]}):
            self.assertEqual(asks.answers(bad), one_tap.YES_NO_LATER, bad)

    def test_its_own_answers_field(self):
        self.assertEqual(asks.answers(dict(ASK, answers=["Approve", "Deny", "Later"])), ("Approve", "Deny", "Later"))
        self.assertEqual(asks.answers(dict(ASK, answers=("Ship", "Wait"))), ("Ship", "Wait"))

    def test_render_ends_in_the_choices_line(self):
        text = asks.render(ASK)
        self.assertEqual(text, "Pick the synthetic plan for\nReply: Yes / No / Later")
        self.assertTrue(one_tap.is_one_tap(text))
        self.assertTrue(one_tap.asks(text))
        own = asks.render(dict(ASK, answers=["Approve", "Deny"]))
        self.assertEqual(own.splitlines()[-1], "Reply: Approve / Deny")

    def test_render_every_kind_and_a_missing_title(self):
        for ask in (ASK, dict(ASK, kind="approval"), dict(ASK, kind="fyi"), dict(ASK, kind="other"), {"id": "x"},
                    dict(ASK, title="Line one\nline two?"), dict(ASK, title="t_510c250d")):
            text = asks.render(ask)
            self.assertTrue(one_tap.is_one_tap(text), text)
            self.assertEqual(len(text.splitlines()), 2, text)
            self.assertNotIn("t_510c250d", text)
        self.assertEqual(asks.render({"id": "x"}).splitlines()[0], asks.NO_TITLE)


class Reply(unittest.TestCase):
    def test_actions_are_plain_words(self):
        self.assertEqual((asks.ANSWERED, asks.REPLY_WAITING), ("answered", "waiting"))
        self.assertEqual(asks.reply(ASK, "Later")["action"], "waiting")
        self.assertEqual(asks.reply(ASK, "Yes")["action"], "answered")
        self.assertEqual(asks.WAITING, "decisions waiting")      # the summary label is unchanged

    def test_a_tap_answers(self):
        r = asks.reply(ASK, "yes.")
        self.assertEqual((r["id"], r["answer"], r["action"]), ("a1", "Yes", asks.ANSWERED))
        self.assertEqual(asks.reply(ASK, "No 👍")["answer"], "No")
        self.assertEqual(asks.reply(ASK, "No")["action"], asks.ANSWERED)

    def test_later_keeps_it_waiting_never_a_no(self):
        for said in ("Later", "later.", "LATER 👍"):
            r = asks.reply(ASK, said)
            self.assertEqual((r["answer"], r["action"]), ("Later", asks.REPLY_WAITING), said)
            self.assertNotIn("no", r["reason"].lower().replace("never a no", "").split())
            self.assertIn("never a no", r["reason"])

    def test_later_in_its_own_answers_is_waiting_too(self):
        r = asks.reply(dict(ASK, answers=["Approve", "Deny", "Later"]), "later")
        self.assertEqual((r["answer"], r["action"]), ("Later", asks.REPLY_WAITING))
        self.assertEqual(asks.reply(dict(ASK, answers=["Approve", "Deny"]), "approve")["answer"], "Approve")

    def test_anything_else_keeps_it_waiting(self):
        for said in ("", None, "maybe", "yes but later", "Approve"):
            r = asks.reply(ASK, said)
            self.assertEqual((r["answer"], r["action"]), (None, asks.REPLY_WAITING), said)

    def test_rows_never_echo_the_reply_and_have_no_card_ids(self):
        r = asks.reply(ASK, "synthetic words here")
        self.assertNotIn("synthetic words", json.dumps(r))
        self.assertNotIn("t_510c250d", json.dumps(asks.reply(ASK, "yes")))

    def test_a_later_ask_stays_pending_and_is_planned_again(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "asks.jsonl"
            p.write_text(json.dumps(ASK) + "\n")
            before = p.read_bytes()
            self.assertEqual(asks.reply(ASK, "Later")["action"], asks.REPLY_WAITING)
            self.assertEqual(p.read_bytes(), before)          # asks.py never writes the queue
            self.assertEqual([r["id"] for r in asks.pending(asks.read(str(p)))], ["a1"])


if __name__ == "__main__":
    unittest.main()
