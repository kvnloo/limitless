"""limitless/delivery_ledger.py: one row per message to one target, its moves, and the day budget.

Synthetic targets only (telegram:synthetic-chat:...); nothing is sent and nothing touches the network.
NOW is an arbitrary epoch; only differences between times matter.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import re
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import delivery_ledger as dl  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NOW = 2_000_000_000.0
H = 3600.0
DAY = NOW - 6 * H          # the caller's budget day started six hours ago
YESTERDAY = DAY - 24 * H
T = "telegram:synthetic-chat:"
T2 = "telegram:synthetic-chat:synthetic-thread"


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ledger.sqlite3"
        self.db = self.connect()

    def connect(self):
        conn = dl.open_ledger(self.path)
        self.addCleanup(conn.close)
        return conn

    def row(self, row_id):
        return dict(self.db.execute("SELECT * FROM delivery WHERE id = ?", (row_id,)).fetchone())

    def fill(self, n, target=T, cls="anytime", at=NOW, cap=dl.DEFAULT_CAP, day=DAY):
        out = [dl.reserve(self.db, target, f"body {i}", day_start=day, now=at, cap=cap, window_class=cls)
               for i in range(n)]
        self.assertTrue(all(r.state == "queued" for r in out), out)
        return out


# --- stage schema
class Schema(LedgerCase):
    def test_one_table_with_the_agreed_columns(self):
        cols = [r[1] for r in self.db.execute("PRAGMA table_info(delivery)")]
        self.assertEqual(cols, ["id", "target", "job_id", "dedup_key", "window_class", "state", "reason", "body",
                                "created_at", "release_after", "sent_at", "reserved_at"])
        tables = [r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        self.assertEqual(tables, ["delivery"])

    def test_the_index_is_target_state_created_at(self):
        idx = [r[1] for r in self.db.execute("PRAGMA index_list(delivery)") if not r[1].startswith("sqlite_")]
        self.assertEqual(len(idx), 1)
        self.assertEqual([r[2] for r in self.db.execute(f"PRAGMA index_info({idx[0]})")],
                         ["target", "state", "created_at"])

    def test_a_state_or_class_outside_the_lists_is_refused_by_the_table(self):
        sql = ("INSERT INTO delivery (target, window_class, state, reason, body, created_at)"
               " VALUES (?, ?, ?, ?, 'b', 0)")
        for cls, state, reason in (("anytime", "lost", "cap"), ("wind_down", "held", "cap"),
                                   ("anytime", "held", "bored"), ("anytime", "held", None)):
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql, (T, cls, state, reason))

    def test_open_twice_keeps_the_rows(self):
        self.db.execute("INSERT INTO delivery (target, window_class, state, reason, body, created_at)"
                        " VALUES (?, 'anytime', 'held', 'cap', 'b', 0)", (T,))
        self.assertEqual(self.connect().execute("SELECT COUNT(*) FROM delivery").fetchone()[0], 1)

    def test_the_doc_shows_the_schema_and_the_budget_query_the_code_runs(self):
        doc = (ROOT / "docs" / "delivery-ledger.md").read_text()
        blocks = re.findall(r"```sql\n(.*?)```", doc, re.S)
        self.assertIn(dl.SCHEMA, blocks)
        flat = [" ".join(b.split()) for b in blocks]
        self.assertTrue(any(f.startswith(" ".join(dl.BUDGET_SQL.split())) for f in flat), flat)


# --- stage reserve
class Reserve(LedgerCase):
    def test_under_the_cap_is_queued_and_takes_its_slot_at_once(self):
        r = dl.reserve(self.db, T, "synthetic body", day_start=DAY, now=NOW, cap=3, job_id="synthetic-job")
        self.assertEqual((r.state, r.reason), ("queued", None))
        self.assertEqual(dl.used(self.db, T, DAY), 1)
        self.assertEqual(self.row(r.id)["reserved_at"], NOW)

    def test_at_the_cap_is_held_with_reason_cap(self):
        self.fill(2, cls="peak", cap=2)
        r = dl.reserve(self.db, T, "one more", day_start=DAY, now=NOW, cap=2, window_class="peak",
                       release_after=NOW + H)
        self.assertEqual((r.state, r.reason), ("held", "cap"))
        self.assertEqual(self.row(r.id)["release_after"], NOW + H)
        self.assertEqual(dl.used(self.db, T, DAY), 2)

    def test_the_budget_is_per_target(self):
        self.fill(2, cls="peak", cap=2)
        self.assertEqual(dl.reserve(self.db, T2, "b", day_start=DAY, now=NOW, cap=2).state, "queued")

    def test_the_callers_quiet_or_sleep_hold_is_kept_and_takes_no_slot(self):
        for why in ("quiet", "sleep"):
            r = dl.reserve(self.db, T, "b", day_start=DAY, now=NOW, hold=why)
            self.assertEqual((r.state, r.reason), ("held", why))
        self.assertEqual(dl.used(self.db, T, DAY), 0)

    def test_bad_arguments_raise(self):
        for kw in ({"window_class": "wind_down"}, {"hold": "cap"}, {"cap": 0}, {"day_start": NOW + 1}):
            args = {"day_start": DAY, "now": NOW, **kw}
            with self.assertRaises(ValueError):
                dl.reserve(self.db, T, "b", **args)
        for target in ("telegram", "telegram:synthetic-chat", ":synthetic-chat:", "telegram::"):
            with self.assertRaises(ValueError):
                dl.reserve(self.db, target, "b", day_start=DAY, now=NOW)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM delivery").fetchone()[0], 0)

    def test_two_connections_racing_on_the_last_slot_queue_exactly_one(self):
        for n in range(8):   # a fresh target per round; each round both threads start together
            target = f"telegram:synthetic-race-{n}:"
            dl.reserve(self.db, target, "first", day_start=DAY, now=NOW, cap=2, window_class="peak")
            gate, out, errors = threading.Barrier(2), [], []

            def go(i):
                conn = dl.open_ledger(self.path)
                try:
                    gate.wait()
                    out.append(dl.reserve(conn, target, f"racer {i}", day_start=DAY, now=NOW, cap=2,
                                          window_class="peak"))
                except Exception as e:  # pragma: no cover - reported below
                    errors.append(e)
                finally:
                    conn.close()

            threads = [threading.Thread(target=go, args=(i,)) for i in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
            self.assertEqual(errors, [])
            self.assertEqual(sorted(r.state for r in out), ["held", "queued"], f"round {n}")
            self.assertEqual(dl.used(self.db, target, DAY), 2)

    def test_the_budget_day_refills_on_the_callers_boundary_not_a_rolling_day(self):
        self.fill(2, cls="peak", cap=2, at=DAY - H, day=YESTERDAY)   # both slots taken an hour before the boundary
        self.assertEqual(dl.used(self.db, T, DAY - 2 * H), 2)
        self.assertEqual(dl.used(self.db, T, DAY), 0)    # a new day: under 24 h later, the budget is full again
        r = dl.reserve(self.db, T, "new day", day_start=DAY, now=DAY + 60, cap=2, window_class="peak")
        self.assertEqual(r.state, "queued")


# --- stage peak
class PeakToken(LedgerCase):
    def test_the_last_slot_is_peaks_alone(self):
        self.fill(2, cap=3)
        for cls in ("anytime", "trough"):
            r = dl.reserve(self.db, T, cls, day_start=DAY, now=NOW, cap=3, window_class=cls)
            self.assertEqual((r.state, r.reason), ("held", "cap"))
        self.assertEqual(dl.reserve(self.db, T, "decide", day_start=DAY, now=NOW, cap=3,
                                    window_class="peak").state, "queued")
        r = dl.reserve(self.db, T, "decide again", day_start=DAY, now=NOW, cap=3, window_class="peak")
        self.assertEqual((r.state, r.reason), ("held", "cap"))   # never borrows from tomorrow
        self.assertEqual(dl.used(self.db, T, DAY), 3)

    def test_peak_may_also_take_an_ordinary_slot(self):
        self.assertEqual(self.fill(1, cls="peak", cap=3)[0].state, "queued")
        self.assertEqual(self.fill(1, cap=3)[0].state, "queued")

    def test_bypass_takes_no_slot_and_is_never_held_for_the_cap(self):
        self.fill(1, cls="peak", cap=1)
        r = dl.reserve(self.db, T, "your schedule card", day_start=DAY, now=NOW, cap=1, window_class="bypass")
        self.assertEqual(r.state, "queued")
        self.assertEqual(dl.used(self.db, T, DAY), 1)


# --- stage moves
class Moves(LedgerCase):
    def queued(self, **kw):
        return dl.reserve(self.db, T, "b", day_start=DAY, now=NOW, **kw).id

    def test_sent_keeps_its_slot(self):
        i = self.queued()
        dl.mark_sent(self.db, i, NOW + 5)
        self.assertEqual((self.row(i)["state"], self.row(i)["sent_at"]), ("sent", NOW + 5))
        self.assertEqual(dl.used(self.db, T, DAY), 1)

    def test_failed_frees_its_slot_and_goes_back_to_held(self):
        ids = [self.queued(window_class="peak", cap=2) for _ in range(2)]
        self.assertEqual(dl.reserve(self.db, T, "c", day_start=DAY, now=NOW, cap=2, window_class="peak").state,
                         "held")
        dl.mark_failed(self.db, ids[0], release_after=NOW + 60)
        row = self.row(ids[0])
        self.assertEqual((row["state"], row["reason"], row["reserved_at"], row["release_after"]),
                         ("held", "failed", None, NOW + 60))
        self.assertEqual(dl.used(self.db, T, DAY), 1)
        self.assertEqual(dl.reserve(self.db, T, "d", day_start=DAY, now=NOW, cap=2, window_class="peak").state,
                         "queued")

    def test_unknown_keeps_its_slot_and_is_never_replayed(self):
        i = self.queued(window_class="peak", cap=1)
        dl.mark_unknown(self.db, i)
        self.assertEqual(self.row(i)["state"], "unknown")
        self.assertEqual(dl.used(self.db, T, DAY), 1)
        self.assertEqual(dl.reserve(self.db, T, "c", day_start=DAY, now=NOW, cap=1, window_class="peak").reason,
                         "cap")
        for move in (lambda: dl.mark_sent(self.db, i, NOW), lambda: dl.mark_failed(self.db, i),
                     lambda: dl.mark_unknown(self.db, i)):
            with self.assertRaises(dl.IllegalTransition):
                move()

    def test_illegal_moves_raise_and_change_nothing(self):
        sent = self.queued()
        dl.mark_sent(self.db, sent, NOW)
        held = dl.reserve(self.db, T, "h", day_start=DAY, now=NOW, hold="quiet").id
        before = [dict(r) for r in self.db.execute("SELECT * FROM delivery ORDER BY id")]
        for move in (lambda: dl.mark_sent(self.db, sent, NOW), lambda: dl.mark_failed(self.db, sent),
                     lambda: dl.mark_unknown(self.db, sent), lambda: dl.mark_sent(self.db, held, NOW),
                     lambda: dl.mark_failed(self.db, held), lambda: dl.mark_unknown(self.db, held),
                     lambda: dl.mark_sent(self.db, 999, NOW)):
            with self.assertRaises(dl.IllegalTransition):
                move()
        self.assertEqual([dict(r) for r in self.db.execute("SELECT * FROM delivery ORDER BY id")], before)

    def test_the_table_refuses_a_slot_on_a_row_that_does_not_hold_one(self):
        i = self.queued()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE delivery SET state = 'held', reason = 'cap' WHERE id = ?", (i,))


# --- stage dedup
class Dedup(LedgerCase):
    def test_a_key_already_queued_sent_or_unknown_is_held_as_dedup(self):
        for n, settle in enumerate((None, "sent", "unknown")):
            key = f"synthetic-event:{n}"
            first = dl.reserve(self.db, T, "first words", day_start=DAY, now=NOW, dedup_key=key)
            if settle == "sent":
                dl.mark_sent(self.db, first.id, NOW)
            elif settle == "unknown":
                dl.mark_unknown(self.db, first.id)
            r = dl.reserve(self.db, T, "other words", day_start=DAY, now=NOW, dedup_key=key,
                           release_after=NOW + H)
            self.assertEqual((r.state, r.reason), ("held", "dedup"), settle)
            self.assertIsNone(self.row(r.id)["release_after"])   # a duplicate never comes due

    def test_dedup_comes_before_the_callers_hold_and_bypass(self):
        dl.reserve(self.db, T, "a", day_start=DAY, now=NOW, dedup_key="k")
        r = dl.reserve(self.db, T, "a", day_start=DAY, now=NOW, dedup_key="k", hold="sleep", window_class="bypass")
        self.assertEqual(r.reason, "dedup")

    def test_another_key_target_or_day_is_not_a_duplicate(self):
        dl.reserve(self.db, T, "a", day_start=DAY - 24 * H, now=DAY - H, dedup_key="k")   # yesterday's
        for target, key in ((T, "k"), (T, "other"), (T2, "k")):
            self.assertEqual(dl.reserve(self.db, target, "a", day_start=DAY, now=NOW, dedup_key=key).state,
                             "queued", (target, key))


# --- stage release
class Release(LedgerCase):
    def test_due_held_lists_rows_whose_release_after_passed_oldest_first(self):
        late = dl.reserve(self.db, T, "late", day_start=DAY, now=NOW, hold="sleep", release_after=NOW + 2 * H).id
        early = dl.reserve(self.db, T, "early", day_start=DAY, now=NOW - H, hold="quiet", release_after=NOW + H).id
        dl.reserve(self.db, T, "no time", day_start=DAY, now=NOW, hold="sleep")
        self.assertEqual(dl.due_held(self.db, NOW), [])
        self.assertEqual([r["id"] for r in dl.due_held(self.db, NOW + 3 * H)], [early, late])

    def test_release_queues_when_a_slot_is_free_else_stays_held_as_cap(self):
        h = dl.reserve(self.db, T, "h", day_start=DAY, now=NOW, cap=1, window_class="peak", hold="sleep").id
        q = dl.reserve(self.db, T, "q", day_start=DAY, now=NOW, cap=1, window_class="peak").id
        self.assertEqual(dl.release(self.db, h, day_start=DAY, now=NOW + 1, cap=1),
                         dl.Reservation(h, "held", "cap"))
        dl.mark_failed(self.db, q)
        self.assertEqual(dl.release(self.db, h, day_start=DAY, now=NOW + 2, cap=1),
                         dl.Reservation(h, "queued", None))
        self.assertEqual(self.row(h)["reserved_at"], NOW + 2)

    def test_a_row_held_yesterday_counts_on_the_day_it_is_released(self):
        h = dl.reserve(self.db, T, "h", day_start=DAY - 24 * H, now=DAY - H, hold="sleep").id
        dl.release(self.db, h, day_start=DAY, now=NOW)
        self.assertEqual(dl.used(self.db, T, DAY), 1)

    def test_sent_unknown_and_dedup_rows_never_come_due(self):
        s = dl.reserve(self.db, T, "s", day_start=DAY, now=NOW, dedup_key="k").id
        dl.mark_sent(self.db, s, NOW)
        dl.mark_unknown(self.db, dl.reserve(self.db, T, "u", day_start=DAY, now=NOW).id)
        dl.reserve(self.db, T, "s", day_start=DAY, now=NOW, dedup_key="k", release_after=NOW)
        self.assertEqual(dl.due_held(self.db, NOW + 365 * 24 * H), [])

    def test_release_of_a_dedup_hold_or_a_row_not_held_raises(self):
        q = dl.reserve(self.db, T, "a", day_start=DAY, now=NOW, dedup_key="k").id
        d = dl.reserve(self.db, T, "a", day_start=DAY, now=NOW, dedup_key="k").id
        for i in (q, d, 999):
            with self.assertRaises(dl.IllegalTransition):
                dl.release(self.db, i, day_start=DAY, now=NOW)
        self.assertEqual(self.row(d)["state"], "held")


if __name__ == "__main__":
    unittest.main()
