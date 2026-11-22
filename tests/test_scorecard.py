"""Scorecard: the hand-kept north-star Markdown table -> rows -> a 5-line weekly-review block.

Synthetic fixtures only (tests/fixtures/scorecard/): invented criteria, no real person's data.
"""
import os
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import scorecard as sc  # noqa: E402
from limitless import tools  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "scorecard"
HEADER = "| # | Criterion | Status | Evidence (latest) | Weeks green |\n|---|---|---|---|---|\n"


def table(*rows):
    return HEADER + "".join(r + "\n" for r in rows)


class Parse(unittest.TestCase):
    def test_fixture_parses_all_ten_rows(self):
        rows = sc.parse((FIX / "scorecard.md").read_text())
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0], {"n": 1, "criterion": "Loop uptime", "status": "green", "weeks_green": 3})
        self.assertEqual(rows[3], {"n": 4, "criterion": "Habit logging", "status": "red", "weeks_green": 0})
        self.assertEqual([r["n"] for r in rows], list(range(1, 11)))

    def test_rows_carry_no_evidence(self):
        for r in sc.parse((FIX / "scorecard.md").read_text()):
            self.assertEqual(set(r), {"n", "criterion", "status", "weeks_green"})
            self.assertNotIn("sentinel", str(r))

    def test_no_table_is_empty(self):
        self.assertEqual(sc.parse(""), [])
        self.assertEqual(sc.parse("# Scorecard\n\nNothing here yet.\n"), [])
        self.assertEqual(sc.parse("| a | b |\n|---|---|\n| 1 | 2 |\n"), [])

    def test_header_without_rows_is_empty(self):
        self.assertEqual(sc.parse(HEADER), [])

    def test_malformed_rows_are_skipped(self):
        rows = sc.parse(table(
            "| 1 | Loop uptime | green | ok | 2 |",
            "| x | Bad number | green | ok | 2 |",
            "| 3 | Bad weeks | green | ok | many |",
            "| 4 | Too few cells | green |",
            "| 5 | Too | many | cells | 1 | 2 |",
            "| 6 |  | green | no criterion | 1 |",
            "| 7 | Delivery | amber | ok | 0 |",
        ))
        self.assertEqual([r["n"] for r in rows], [1, 7])

    def test_unknown_status_reads_unknown(self):
        rows = sc.parse(table("| 1 | Loop uptime | blue | ok | 0 |", "| 2 | Delivery |  | ok | 0 |"))
        self.assertEqual([r["status"] for r in rows], ["unknown", "unknown"])

    def test_status_case_and_spacing_are_normalised(self):
        rows = sc.parse(table("|  1  |  Loop uptime  |  Green  | ok |  3  |", "|2|Delivery|AMBER|ok|0|"))
        self.assertEqual(rows, [{"n": 1, "criterion": "Loop uptime", "status": "green", "weeks_green": 3},
                                {"n": 2, "criterion": "Delivery", "status": "amber", "weeks_green": 0}])

    def test_table_ends_at_the_first_non_table_line(self):
        rows = sc.parse(table("| 1 | Loop uptime | green | ok | 3 |") + "\nprose\n| 2 | Delivery | red | ok | 0 |\n")
        self.assertEqual([r["n"] for r in rows], [1])

    def test_rows_without_outer_pipes_still_parse(self):
        rows = sc.parse("# | Criterion | Status | Evidence (latest) | Weeks green\n---|---|---|---|---\n"
                        "1 | Loop uptime | red | ok | 0\n")
        self.assertEqual(rows, [{"n": 1, "criterion": "Loop uptime", "status": "red", "weeks_green": 0}])


def row(n, criterion, status, weeks=0):
    return {"n": n, "criterion": criterion, "status": status, "weeks_green": weeks}


class Summary(unittest.TestCase):
    def test_fixture_summary(self):
        lines = sc.summary(sc.parse((FIX / "scorecard.md").read_text()))
        self.assertEqual(lines, ["6 green, 2 amber, 2 red of 10", "not all green yet",
                                 "Habit logging: red", "Experiment readout: red", "Delivery: amber"])

    def test_no_rows_no_lines(self):
        self.assertEqual(sc.summary([]), [])

    def test_at_most_five_lines(self):
        rows = [row(i, f"Criterion {chr(64 + i)}", "red") for i in range(1, 11)]
        self.assertEqual(len(sc.summary(rows)), 5)

    def test_red_before_amber_then_lowest_number(self):
        rows = [row(9, "Delivery", "amber"), row(7, "Loop uptime", "red"), row(2, "Review held", "amber"),
                row(8, "Notes current", "red"), row(1, "Capture triage", "green", 3)]
        self.assertEqual(sc.summary(rows)[2:], ["Loop uptime: red", "Notes current: red", "Review held: amber"])

    def test_unknown_ranks_after_amber_and_counts_only_in_the_total(self):
        rows = [row(1, "Loop uptime", "unknown"), row(2, "Delivery", "amber"), row(3, "Review held", "green", 2)]
        self.assertEqual(sc.summary(rows), ["1 green, 1 amber, 0 red of 3", "not all green yet",
                                            "Delivery: amber", "Loop uptime: unknown"])

    def test_all_green_uses_the_minimum_weeks(self):
        rows = [row(1, "Loop uptime", "green", 3), row(2, "Delivery", "green", 1), row(3, "Review held", "green", 9)]
        self.assertEqual(sc.summary(rows), ["3 green, 0 amber, 0 red of 3", "all green for 1 of 4 weeks"])

    def test_weeks_are_capped_at_four_and_never_declared_met(self):
        rows = [row(1, "Loop uptime", "green", 7), row(2, "Delivery", "green", 5)]
        lines = sc.summary(rows)
        self.assertEqual(lines[1], "all green for 4 of 4 weeks")
        for word in ("met", "achieved", "done", "success"):
            self.assertNotIn(word, " ".join(lines).lower())

    def test_no_evidence_text(self):
        text = "\n".join(sc.summary(sc.parse((FIX / "scorecard.md").read_text())))
        self.assertNotIn("sentinel", text)

    def test_criterion_digits_masked_and_card_ids_removed(self):
        rows = [row(1, "Sleep 7 h t_510c250d", "red"), row(2, "Delivery 2026", "amber", 0)]
        lines = sc.summary(rows)
        self.assertEqual(lines[2:], ["Sleep # h: red", "Delivery #: amber"])
        self.assertNotIn("t_510c250d", " ".join(lines))

    def test_only_counts_and_week_numbers_are_digits(self):
        import re
        rows = sc.parse((FIX / "scorecard.md").read_text()) + [row(11, "Window 12 to 14", "red")]
        lines = sc.summary(rows)
        self.assertEqual(re.findall(r"\d+", " ".join(lines[2:])), [])
        self.assertEqual(re.findall(r"\d+", lines[0]), ["6", "2", "3", "11"])
        self.assertEqual(re.findall(r"\d+", lines[1]), [])

    def test_parenthetical_thresholds_are_dropped(self):
        lines = sc.summary(sc.parse((FIX / "thresholds.md").read_text()))
        self.assertEqual(lines, ["1 green, 2 amber, 2 red of 5", "not all green yet",
                                 "Loop uptime: red", "Review held: red", "Delivery: amber"])

    def test_nested_and_unbalanced_parentheses(self):
        rows = [row(1, "Review held (weekly, within 2 days (grace 1))", "red"),
                row(2, "Notes current (updated <3 d", "red"),
                row(3, "Window kept) by 9 (+-1 h)", "red")]
        self.assertEqual(sc.summary(rows)[2:], ["Review held: red", "Notes current: red", "Window kept by #: red"])

    def test_text_around_a_parenthetical_is_kept(self):
        rows = [row(1, "Sleep (>=7 h) logged 5 days", "red"), row(2, "Inbox (<10) triaged t_510c250d", "amber")]
        self.assertEqual(sc.summary(rows)[2:], ["Sleep logged # days: red", "Inbox triaged: amber"])

    def test_name_that_is_only_a_parenthetical_falls_back_to_masked_text(self):
        rows = [row(5, "(90% of 7 days)", "amber"), row(6, "()", "red")]
        self.assertEqual(sc.summary(rows)[2:], ["(): red", "(#% of # days): amber"])

    def test_threshold_fixture_shows_no_digits_in_names(self):
        import re
        lines = sc.summary(sc.parse((FIX / "thresholds.md").read_text()))
        self.assertEqual(re.findall(r"[\d(<>=%]", " ".join(lines[2:])), [])

    def test_lines_are_plain_words(self):
        for ln in sc.summary(sc.parse((FIX / "scorecard.md").read_text())):
            self.assertNotRegex(ln, r"[|*_`\[\]]")
            self.assertEqual(ln, ln.strip())


class WeeklyBlock(unittest.TestCase):
    def test_fixture_block(self):
        block = sc.weekly_block(sc.summary(sc.parse((FIX / "thresholds.md").read_text())))
        self.assertEqual(block, "North star (self-reported)\n"
                                "- 1 green, 2 amber, 2 red of 5\n"
                                "- not all green yet\n"
                                "- Loop uptime: red\n"
                                "- Review held: red\n"
                                "- Delivery: amber")

    def test_no_lines_is_empty(self):
        self.assertEqual(sc.weekly_block([]), "")
        self.assertEqual(sc.weekly_block(["", "   "]), "")

    def test_at_most_six_lines(self):
        block = sc.weekly_block([f"line {chr(97 + i)}" for i in range(9)])
        self.assertEqual(len(block.splitlines()), 6)
        self.assertEqual(block.splitlines()[0], "North star (self-reported)")
        self.assertTrue(all(ln.startswith("- ") for ln in block.splitlines()[1:]))

    def test_never_says_met_or_achieved(self):
        import re
        rows = [row(1, "Targets met", "green", 9), row(2, "Goal achieved", "green", 9)]
        block = sc.weekly_block(sc.summary(rows) + ["Targets met: red", "Goal ACHIEVED (early): amber"])
        self.assertEqual(re.findall(r"(?i)\b(met|achieved)\b", block), [])
        self.assertIn("- Targets: red", block)

    def test_lines_are_stripped(self):
        self.assertEqual(sc.weekly_block(["  Delivery: amber  "]), "North star (self-reported)\n- Delivery: amber")


class Tool(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)
        self.dir = Path(self._d.name)

    def card(self, text, mtime=1894708800.0):
        p = self.dir / "scorecard.md"
        p.write_text(text)
        os.utime(p, (mtime, mtime))
        return p

    def test_summary_in_a_self_report_envelope_aged_by_mtime(self):
        p = self.card((FIX / "scorecard.md").read_text(), mtime=1894708800.0)
        env = tools.scorecard(p, 1894708800.0 + 6 * 3600)
        self.assertEqual(env["modality"], "self_report")
        self.assertEqual(env["age_h"], 6.0)
        self.assertEqual(env["evidence_tier"], "direct")
        self.assertEqual(env["value"], sc.summary(sc.parse((FIX / "scorecard.md").read_text())))

    def test_a_week_old_card_is_stale_not_hidden(self):
        p = self.card((FIX / "scorecard.md").read_text(), mtime=1894708800.0)
        env = tools.scorecard(p, 1894708800.0 + 7 * 86400)
        self.assertEqual(env["evidence_tier"], "stale")
        self.assertEqual(env["age_h"], 168.0)
        self.assertEqual(len(env["value"]), 5)

    def test_missing_file_is_missing(self):
        env = tools.scorecard(self.dir / "nope.md", 1894708800.0)
        self.assertIsNone(env["value"])
        self.assertEqual(env["evidence_tier"], "none")
        self.assertTrue(env["reason"])
        self.assertNotIn(str(self.dir), env["reason"])

    def test_no_path_is_missing(self):
        env = tools.scorecard(None, 1894708800.0)
        self.assertIsNone(env["value"])
        self.assertIn("LIMITLESS_SCORECARD", env["reason"])

    def test_file_without_a_table_has_no_value(self):
        p = self.card("# Scorecard\n\nnot started\n")
        env = tools.scorecard(p, 1894708800.0 + 3600)
        self.assertIsNone(env["value"])
        self.assertEqual(env["modality"], "self_report")
        self.assertEqual(env["age_h"], 1.0)
        self.assertTrue(env["reason"])

    def test_future_mtime_reads_as_age_zero(self):
        p = self.card((FIX / "scorecard.md").read_text(), mtime=1894708800.0 + 60)
        self.assertEqual(tools.scorecard(p, 1894708800.0)["age_h"], 0.0)


class Path_(unittest.TestCase):
    def test_env_wins(self):
        self.assertEqual(sc.path({"LIMITLESS_SCORECARD": "card.md"}, Path("nohome")), Path("card.md"))

    def test_config_key(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"scorecard": "from-config.md"}))
            self.assertEqual(sc.path({"LIMITLESS_CONFIG": str(cfg)}, Path(d)), Path("from-config.md"))
            home = Path(d) / "home"
            (home / ".config/limitless").mkdir(parents=True)
            (home / ".config/limitless/config.json").write_text(json.dumps({"scorecard": "home.md"}))
            self.assertEqual(sc.path({}, home), Path("home.md"))

    def test_neither_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(sc.path({}, Path(d)))
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"scorecard": 3}))
            self.assertIsNone(sc.path({"LIMITLESS_CONFIG": str(cfg)}, Path(d)))


if __name__ == "__main__":
    unittest.main()
