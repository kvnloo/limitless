"""limitless.blocks: focus blocks from activity rows (pure), the current block, and the AW DB read.

Synthetic rows only; app names are made up. Times are epoch seconds picked for the test; nothing reads the clock.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import blocks  # noqa: E402
from test_flow_week import make_db  # noqa: E402

T0 = 2_000_000_000.0
M = 60.0
WORK = ("editor", "title:notes")
GAP = 10 * M


def row(start_m, end_m, app="editor", title=""):
    return {"start": T0 + start_m * M, "end": T0 + end_m * M, "app": app, "package": "org.example." + app,
            "title": title}


class FocusBlocks(unittest.TestCase):
    def test_no_work_apps_is_unknown_never_zero(self):
        rows = [row(0, 120)]
        self.assertIsNone(blocks.focus_blocks(rows, (), GAP))
        self.assertIsNone(blocks.focus_blocks(rows, None, GAP))
        self.assertIsNone(blocks.focus_blocks(rows, ("  ", "title:"), GAP))

    def test_known_apps_and_no_work_rows_is_no_block(self):
        self.assertEqual(blocks.focus_blocks([row(0, 30, "scroller")], WORK, GAP), [])
        self.assertEqual(blocks.focus_blocks([], WORK, GAP), [])

    def test_no_rows_at_all_is_unknown(self):
        self.assertIsNone(blocks.focus_blocks(None, WORK, GAP))

    def test_one_block_from_contiguous_work(self):
        rows = [row(0, 40), row(40, 100)]
        self.assertEqual(blocks.focus_blocks(rows, WORK, GAP), [(T0, T0 + 100 * M)])

    def test_a_block_survives_a_short_non_work_gap(self):
        rows = [row(0, 50), row(50, 55, "scroller"), row(55, 120)]
        self.assertEqual(blocks.focus_blocks(rows, WORK, GAP), [(T0, T0 + 120 * M)])
        # an idle gap (no row at all) shorter than gap_s is kept too
        self.assertEqual(blocks.focus_blocks([row(0, 50), row(58, 120)], WORK, GAP), [(T0, T0 + 120 * M)])

    def test_a_long_gap_splits_blocks(self):
        rows = [row(0, 50), row(50, 80, "scroller"), row(80, 120)]
        self.assertEqual(blocks.focus_blocks(rows, WORK, GAP), [(T0, T0 + 50 * M), (T0 + 80 * M, T0 + 120 * M)])

    def test_title_and_package_match_case_folded(self):
        rows = [{"start": T0, "end": T0 + 30 * M, "app": "Browser", "title": "My NOTES page"},
                {"start": T0 + 30 * M, "end": T0 + 60 * M, "app": "", "package": "ORG.EXAMPLE.EDITOR"}]
        self.assertEqual(blocks.focus_blocks(rows, ("title:notes", "org.example.editor"), GAP),
                         [(T0, T0 + 60 * M)])

    def test_unsorted_overlapping_and_bad_rows(self):
        rows = [row(60, 90), {"start": "x", "end": T0}, None, {"start": T0 + 5, "end": T0}, row(0, 70)]
        self.assertEqual(blocks.focus_blocks(rows, WORK, GAP), [(T0, T0 + 90 * M)])

    def test_reader_rows_with_names(self):
        rows = [{"start": T0, "end": T0 + 30 * M, "names": ["editor"], "title": ""}]
        self.assertEqual(blocks.focus_blocks(rows, WORK, GAP), [(T0, T0 + 30 * M)])


class CurrentBlock(unittest.TestCase):
    B = [(T0, T0 + 50 * M), (T0 + 80 * M, T0 + 120 * M)]

    def test_the_latest_block_is_current_within_the_gap(self):
        self.assertEqual(blocks.current_block(self.B, T0 + 125 * M, gap_s=GAP), self.B[1])
        self.assertEqual(blocks.current_block(self.B, T0 + 100 * M, gap_s=GAP), self.B[1])

    def test_no_block_once_the_gap_has_passed(self):
        self.assertIsNone(blocks.current_block(self.B, T0 + 131 * M, gap_s=GAP))

    def test_unknown_and_empty(self):
        self.assertIsNone(blocks.current_block(None, T0))
        self.assertIsNone(blocks.current_block([], T0))

    def test_a_block_in_the_future_is_not_current(self):
        self.assertIsNone(blocks.current_block([(T0 + M, T0 + 2 * M)], T0))


class LongBlockEvents(unittest.TestCase):
    def test_one_event_per_block_past_the_threshold(self):
        bs = [(T0, T0 + 50 * M), (T0 + 80 * M, T0 + 200 * M)]
        evs = blocks.long_block_events(bs, 90 * M)
        self.assertEqual(evs, [{"event": "long_block", "at": T0 + 170 * M, "block_start": T0 + 80 * M,
                                "block_end": T0 + 200 * M}])

    def test_exactly_the_threshold_counts_and_unknown_is_none(self):
        self.assertEqual(len(blocks.long_block_events([(T0, T0 + 90 * M)], 90 * M)), 1)
        self.assertEqual(blocks.long_block_events([(T0, T0 + 89 * M)], 90 * M), [])
        self.assertEqual(blocks.long_block_events(None, 90 * M), [])


class Config(unittest.TestCase):
    def test_defaults_and_overrides(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "c.json"
            env = {"LIMITLESS_CONFIG": str(cfg)}
            self.assertEqual(blocks.break_after_s(env), 90 * M)
            self.assertEqual(blocks.gap_s(env), blocks.GAP_S)
            cfg.write_text('{"break_after_min": 120, "block_gap_min": 5}')
            self.assertEqual(blocks.break_after_s(env), 120 * M)
            self.assertEqual(blocks.gap_s(env), 5 * M)
            for bad in ('"soon"', "0", "-3", "true"):
                cfg.write_text('{"break_after_min": %s, "block_gap_min": %s}' % (bad, bad))
                self.assertEqual(blocks.break_after_s(env), 90 * M, bad)
                self.assertEqual(blocks.gap_s(env), blocks.GAP_S, bad)


class ReadRows(unittest.TestCase):
    def test_rows_from_an_aw_db_cut_to_not_afk(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "aw.db"
            make_db(db, spans=[(T0, T0 + 60 * M, "editor")],
                    afk=[(T0, T0 + 40 * M, "not-afk"), (T0 + 40 * M, T0 + 60 * M, "afk")])
            rows = blocks.read_rows(db, T0 - 3600, T0 + 3 * 3600)
            self.assertEqual(blocks.focus_blocks(rows, WORK, GAP), [(T0, T0 + 40 * M)])

    def test_rows_without_afk_data_are_kept_whole(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "aw.db"
            make_db(db, spans=[(T0, T0 + 60 * M, "editor"), (T0 + 60 * M, T0 + 70 * M, "scroller")])
            rows = blocks.read_rows(db, T0 - 3600, T0 + 3 * 3600)
            self.assertEqual(blocks.focus_blocks(rows, WORK, GAP), [(T0, T0 + 60 * M)])

    def test_missing_or_broken_db_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(blocks.read_rows(None, T0, T0 + 1))
            self.assertIsNone(blocks.read_rows(Path(d) / "nope.db", T0, T0 + 1))
            bad = Path(d) / "bad.db"
            bad.write_text("not a db")
            self.assertIsNone(blocks.read_rows(bad, T0, T0 + 1))


if __name__ == "__main__":
    unittest.main()
