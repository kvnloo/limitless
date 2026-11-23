"""limitless/voice_miq.py: the MIQ answered by voice, read from a z0live call's session events.

Synthetic transcripts only. The row shape is z0live's ``sessions/SESSION_ID.jsonl`` export (docs/API.md
``POST /v1/events``; desktop/z0live_desktop/core.py ``export_events``): ``{"id", "session_id", "ts", "type",
"text", "data"}``. Nothing sends.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import voice_miq  # noqa: E402

Q = "Do you know the one thing that matters most tomorrow?"


def ev(i, kind, text, **data):
    return {"id": i, "session_id": "s-test", "ts": 1894708800.0 + i, "type": kind, "text": text, "data": data}


def call(*turns):
    """[("a"|"u", text), ...] -> session rows, assistant/user transcripts in order."""
    kinds = {"a": "assistant_transcript", "u": "user_transcript"}
    return [ev(i + 1, kinds[who], text) for i, (who, text) in enumerate(turns)]


class AnswerFrom(unittest.TestCase):
    def test_no_miq_asked_is_none(self):
        t = call(("u", "hey"), ("a", "Hi, what is up?"), ("u", "nothing much"))
        self.assertIsNone(voice_miq.answer_from(t, Q))

    def test_asked_but_silent_is_none(self):
        t = call(("u", "hey"), ("a", "Hi. " + Q))
        self.assertIsNone(voice_miq.answer_from(t, Q))

    def test_asked_then_the_assistant_talks_on_is_none(self):
        t = call(("a", Q), ("a", "No rush."), ("u", ""))
        self.assertIsNone(voice_miq.answer_from(t, Q))

    def test_one_answer_turn(self):
        t = call(("u", "hey"), ("a", "Before we go on: " + Q), ("u", "Yes, the draft review"),
                 ("a", "Got it."))
        self.assertEqual(voice_miq.answer_from(t, Q), "Yes, the draft review")

    def test_two_answer_turns_joined(self):
        t = call(("a", Q), ("u", "yes"), ("u", "  it is the  draft review "), ("a", "Saved."),
                 ("u", "something else entirely"))
        self.assertEqual(voice_miq.answer_from(t, Q), "yes it is the draft review")

    def test_question_matches_without_case_or_punctuation(self):
        t = call(("a", "so... do you KNOW the one thing, that matters most tomorrow"), ("u", "later"))
        self.assertEqual(voice_miq.answer_from(t, Q), "later")

    def test_a_paraphrase_is_not_the_miq(self):
        t = call(("a", "What is your main thing for tomorrow?"), ("u", "the review"))
        self.assertIsNone(voice_miq.answer_from(t, Q))

    def test_partial_transcripts_and_other_events_are_skipped(self):
        t = call(("a", Q))
        t += [ev(2, "user_transcript", "ye", final=False), ev(3, "floor", "", state="user"),
              ev(4, "user_transcript", "yes the review"), ev(5, "tool_call", "", name="x")]
        self.assertEqual(voice_miq.answer_from(t, Q), "yes the review")

    def test_rows_are_read_in_id_order(self):
        t = call(("a", Q), ("u", "first"), ("u", "second"))
        self.assertEqual(voice_miq.answer_from(list(reversed(t)), Q), "first second")

    def test_asked_twice_the_later_answer_wins(self):
        t = call(("a", Q), ("u", "hmm no"), ("a", "Sure? " + Q), ("u", "yes, the review"))
        self.assertEqual(voice_miq.answer_from(t, Q), "yes, the review")

    def test_asked_again_but_silent_keeps_the_earlier_answer(self):
        t = call(("a", Q), ("u", "yes, the review"), ("a", Q))
        self.assertEqual(voice_miq.answer_from(t, Q), "yes, the review")

    def test_bad_input_is_none_never_raises(self):
        for t, q in ((None, Q), ("text", Q), ([1, None, "x", {"type": "user_transcript"}], Q),
                     (call(("a", Q), ("u", "yes")), ""), (call(("a", Q), ("u", "yes")), None),
                     ([{"type": "assistant_transcript", "text": None}, {"type": "user_transcript", "text": 7}], Q)):
            self.assertIsNone(voice_miq.answer_from(t, q), t)

    def test_pure_input_untouched(self):
        t = call(("a", Q), ("u", "yes"))
        before = repr(t)
        voice_miq.answer_from(t, Q)
        self.assertEqual(repr(t), before)


if __name__ == "__main__":
    unittest.main()
