"""docs/delivery-ledger.md: the schema, the allowed moves, the budget query, bypass and the open questions."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "delivery-ledger.md"


class Docs(unittest.TestCase):
    def text(self):
        return " ".join(DOC.read_text().split())

    def test_the_doc_has_its_sections(self):
        heads = re.findall(r"^## (.+)$", DOC.read_text(), re.M)
        for want in ("Schema", "States and moves", "The budget", "Held rows", "Bypass", "Open questions for review"):
            self.assertIn(want, heads)

    def test_the_doc_says_the_rules(self):
        want = ("CREATE TABLE", "CREATE INDEX", "(target, state, created_at)", "BEGIN IMMEDIATE",
                "WHERE id = ? AND state = ?", "state IN ('queued', 'sent', 'unknown')", "IllegalTransition",
                "never a rolling 24 h", "reserved last token", "frees its slot", "never replayed",
                "never deleted", "Nothing is wired yet", "platform:chat_id:thread_id")
        text = self.text()
        for w in want:
            self.assertIn(w, text)

    def test_the_doc_names_every_move(self):
        text = self.text()
        for call in ("reserve", "mark_sent", "mark_unknown", "mark_failed", "release", "due_held", "expire_old"):
            self.assertIn(f"`{call}", text)

    def test_bypass_lists_who_may_use_it(self):
        bypass = DOC.read_text().split("## Bypass", 1)[1].split("\n## ", 1)[0]
        for who in ("failure alerts", "schedule and change cards", "one-shot", "replies"):
            self.assertIn(who, bypass)

    def section(self, head):
        return " ".join(DOC.read_text().split(f"\n## {head}\n", 1)[1].split("\n## ", 1)[0].split())

    def test_why_describes_kevin_push_as_it_is_on_main(self):
        why = self.section("Why")
        self.assertNotIn("no lock", why)   # read -> decide -> reserve runs under one flock on main
        for w in ("flock", "pending", "unknown", "token", "rolling 24 h", "`sent.json`", "`held.jsonl`",
                  "no state column"):
            self.assertIn(w, why)

    def test_the_open_questions_ask_at_least_these(self):
        qs = DOC.read_text().split("## Open questions for review", 1)[1]
        for q in ("Digest body cap", "Max hold age default", "What a bypass counts against"):
            self.assertIn(q, qs)


if __name__ == "__main__":
    unittest.main()
