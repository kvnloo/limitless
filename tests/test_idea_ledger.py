"""idea_ledger core: captures not yet in the one idea ledger, as append-only rows. Synthetic fixtures only."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import idea_ledger  # noqa: E402

A = {"at": "2030-01-07T21:00:00+00:00", "text": "Synthetic idea about a reading lamp", "source": "hermes"}
B = {"at": "2030-01-07T22:30:00+00:00", "text": "Another synthetic idea", "source": "bedtime"}
C = {"at": "2030-01-08T09:00:00+00:00", "text": "A third synthetic idea", "source": "hermes"}


class NewRows(unittest.TestCase):
    def test_every_capture_becomes_one_new_idea_row(self):
        rows = idea_ledger.new_rows([A, B], [], None)
        self.assertEqual([r["text"] for r in rows], [A["text"], B["text"]])
        for r, c in zip(rows, (A, B)):
            self.assertEqual(set(r), {"kind", "id", "at", "text", "source", "status"})
            self.assertEqual((r["kind"], r["status"], r["at"], r["source"]), ("idea", "new", c["at"], c["source"]))
            self.assertEqual(r["id"], idea_ledger.idea_id(c["text"]))

    def test_a_rerun_appends_nothing(self):
        first = idea_ledger.new_rows([A, B], [], None)
        self.assertEqual(idea_ledger.new_rows([A, B], first, None), [])

    def test_dedupe_is_on_normalised_text(self):
        same = dict(A, at="2030-01-09T08:00:00+00:00", text="  synthetic IDEA about a\n reading   lamp ")
        self.assertEqual(idea_ledger.idea_id(same["text"]), idea_ledger.idea_id(A["text"]))
        ledger = idea_ledger.new_rows([A], [], None)
        self.assertEqual(idea_ledger.new_rows([A, same, C], ledger, None), idea_ledger.new_rows([C], [], None))

    def test_the_same_text_twice_in_one_batch_is_one_row(self):
        self.assertEqual(len(idea_ledger.new_rows([A, dict(A, at=B["at"])], [], None)), 1)

    def test_id_is_a_stable_short_hash_without_the_text(self):
        i = idea_ledger.idea_id(A["text"])
        self.assertRegex(i, r"^idea_[0-9a-f]{16}$")
        self.assertEqual(i, idea_ledger.idea_id(A["text"].upper()))
        self.assertNotEqual(i, idea_ledger.idea_id(B["text"]))

    def test_cursor_skips_captures_at_or_before_it(self):
        rows = idea_ledger.new_rows([A, B, C], [], B["at"])
        self.assertEqual([r["text"] for r in rows], [C["text"]])

    def test_cursor_of_a_ledger_is_its_newest_idea_time(self):
        self.assertIsNone(idea_ledger.cursor([]))
        ledger = idea_ledger.new_rows([B, A], [], None)
        self.assertEqual(idea_ledger.cursor(ledger + [{"kind": "note", "at": "2031-01-01T00:00:00+00:00"}]), B["at"])

    def test_an_idea_the_person_removed_is_not_appended_again(self):
        ledger = idea_ledger.new_rows([A, B], [], None)
        kept = [r for r in ledger if r["text"] != A["text"]]     # the person dropped A in a review
        self.assertEqual(idea_ledger.new_rows([A, B, C], kept, idea_ledger.cursor(kept)),
                         idea_ledger.new_rows([C], [], None))

    def test_bad_captures_are_skipped(self):
        bad = [None, "text", {}, {"text": ""}, {"text": "   "}, {"text": 7, "at": A["at"]},
               {"text": "no time"}, {"text": "bad time", "at": "yesterday"}, dict(A, source=None)]
        rows = idea_ledger.new_rows(bad, [], None)
        self.assertEqual([r["text"] for r in rows], [A["text"]])
        self.assertEqual(rows[0]["source"], "unknown")

    def test_existing_rows_are_never_changed_or_reordered(self):
        ledger = [{"kind": "idea", "id": "idea_x", "at": C["at"], "text": "kept", "source": "hermes",
                   "status": "parked"}, {"kind": "idea", "id": "idea_y", "at": A["at"], "text": "old",
                                         "source": "hermes", "status": "new"}]
        before = [dict(r) for r in ledger]
        idea_ledger.new_rows([A, B, C], ledger, None)
        self.assertEqual(ledger, before)

    def test_new_rows_come_in_capture_time_order_and_inputs_untouched(self):
        caps = [C, A, B]
        before = [dict(c) for c in caps]
        rows = idea_ledger.new_rows(caps, [], None)
        self.assertEqual([r["at"] for r in rows], [A["at"], B["at"], C["at"]])
        self.assertEqual(caps, before)


if __name__ == "__main__":
    unittest.main()
