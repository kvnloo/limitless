"""The explain-back reply: saved through the one capture path as kind explain_back, so it reaches the idea ledger
when one is set. Never graded, never followed up; Later is not logged. ``unknowns`` holds only the person's own
"I could not explain X" words, verbatim. Synthetic text only.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import capture, explain_back, idea_ledger, plugin  # noqa: E402

NOW = 1894708800.0
ANSWER = "The parser now reads the new field and the old files still load. I could not explain the retry path."


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name) / "st"
        self.st.mkdir()

    def rows(self):
        p = self.st / capture.FILE
        return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []


class Unknowns(unittest.TestCase):
    def test_only_the_persons_own_words(self):
        self.assertEqual(explain_back.unknowns(ANSWER), ["I could not explain the retry path."])
        self.assertEqual(explain_back.unknowns("i couldn't explain why the cache helps! Rest is clear"),
                         ["i couldn't explain why the cache helps!"])
        two = "I could not explain X. Fine otherwise. I could not explain Y"
        self.assertEqual(explain_back.unknowns(two), ["I could not explain X.", "I could not explain Y"])

    def test_nothing_derived_otherwise(self):
        for text in ("It all landed.", "I am not sure about the retry path.", "", None, 7):
            self.assertEqual(explain_back.unknowns(text), [], text)


class Reply(Base):
    def test_an_answer_is_one_capture_of_kind_explain_back(self):
        out = explain_back.reply(self.st, ANSWER, NOW)
        self.assertEqual(out["value"], {"captured": True, "line": 1})
        self.assertEqual(out["modality"], "self_report")
        (row,) = self.rows()
        self.assertEqual(row["kind"], "explain_back")
        self.assertEqual(row["text"], ANSWER)                      # verbatim, never rewritten
        self.assertEqual(row["unknowns"], ["I could not explain the retry path."])
        self.assertEqual(sorted(row), ["at", "kind", "source", "text", "unknowns"])   # no grade, no score
        self.assertNotIn(ANSWER, json.dumps(out))                    # the result never echoes the text

    def test_no_unknowns_no_field(self):
        explain_back.reply(self.st, "The parser reads the new field.", NOW)
        self.assertNotIn("unknowns", self.rows()[0])

    def test_later_and_a_bare_voice_tap_log_nothing(self):
        for text in ("Later", "later.", "LATER 👍", "Voice", "voice."):
            out = explain_back.reply(self.st, text, NOW)
            self.assertIsNone(out["value"], text)
            self.assertFalse(any(c.isdigit() for c in out["reason"]))
        self.assertEqual(self.rows(), [])                            # skipped = unlogged

    def test_empty_logs_nothing(self):
        for text in ("", "   ", None):
            self.assertIsNone(explain_back.reply(self.st, text, NOW)["value"])
        self.assertEqual(self.rows(), [])

    def test_the_reason_never_asks_a_follow_up(self):
        for text in ("Later", "Voice"):
            self.assertNotIn("?", explain_back.reply(self.st, text, NOW)["reason"])


class Capture(Base):
    def test_plain_capture_is_unchanged(self):
        capture.capture(self.st, "a synthetic idea", NOW)
        self.assertEqual(sorted(self.rows()[0]), ["at", "source", "text"])

    def test_an_unknown_kind_records_nothing(self):
        out = capture.capture(self.st, "a synthetic idea", NOW, kind="quiz")
        self.assertIsNone(out["value"])
        self.assertEqual(self.rows(), [])


class Ledger(Base):
    def test_the_answer_lands_in_the_one_idea_ledger(self):
        explain_back.reply(self.st, ANSWER, NOW)
        ledger = Path(self.tmp.name) / "ideas.jsonl"
        env = {"LIMITLESS_IDEA_LEDGER": str(ledger), "LIMITLESS_CONFIG": str(Path(self.tmp.name) / "none.json")}
        out = idea_ledger.run(self.st, env=env, write=True)
        self.assertEqual(out["count"], 1)
        (row,) = [json.loads(ln) for ln in ledger.read_text().splitlines()]
        self.assertEqual((row["text"], row["status"]), (ANSWER, "new"))


class Tool(Base):
    def test_limitless_capture_takes_kind_explain_back(self):
        schema, fn, _ = plugin.TOOLS["limitless_capture"]
        self.assertEqual(schema["parameters"]["properties"]["kind"]["enum"], ["explain_back"])
        env = {"LIMITLESS_STATE": str(self.st)}
        import os
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            fn({"text": ANSWER, "kind": "explain_back"}, NOW)
            fn({"text": "Later", "kind": "explain_back"}, NOW)
            fn({"text": "a synthetic idea"}, NOW)
        finally:
            for k, v in old.items():
                os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)
        self.assertEqual([r.get("kind") for r in self.rows()], ["explain_back", None])


if __name__ == "__main__":
    unittest.main()
