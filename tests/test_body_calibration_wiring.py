"""body_calibration wired into the body trend, limitless_body and the week review line.

Synthetic rows only. Config ``body_calibration`` is ``on`` by default, which changes something only when a
fit exists; ``off`` is exactly the trend from before calibration existed. The fit's numbers never leave code.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import body, body_calibration as bc, jobs_runner, tier_audit, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

TODAY = date(2030, 1, 28)
NOW = datetime.combine(TODAY, time(12)).timestamp()
FITTED_DOWN = "body fat trending down (calibrated against reference scans)"
NO_FIT_SENTENCE = "Uncalibrated: fewer than two reference scans paired with a scale reading."


def row(days_ago, bf, method="synthetic-scale", calibrated=False):
    return {"day": (TODAY - timedelta(days=days_ago)).isoformat(), "bf_pct": float(bf), "method": method,
            "calibrated": calibrated}


def scale_rows():
    """Uncalibrated scale rows: three in the prior window, three in the recent one, about a point lower."""
    return [row(27, 18.0), row(25, 18.2), row(23, 17.9), row(13, 17.0), row(11, 17.1), row(9, 16.9)]


def with_refs(n=2):
    refs = [row(26, 22.0, "dxa", True), row(12, 21.0, "dxa", True)][:n]
    return sorted(scale_rows() + refs, key=lambda r: r["day"])


def thin_recent():
    """Two scans paired, but only two rows in the recent window: not enough measurements."""
    drop = {row(11, 0)["day"], row(9, 0)["day"]}
    return [r for r in with_refs() if r["method"] == "dxa" or r["day"] not in drop]


def has_digit(v) -> bool:
    return bool(re.search(r"\d", json.dumps(v)))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_STATE": str(self.st)}
        self.configure()

    def configure(self, **extra):
        self.cfg.write_text(json.dumps(dict({"body_file": "body.jsonl"}, **extra)))

    def write(self, data):
        (self.st / "body.jsonl").write_text("".join(json.dumps(r) + "\n" for r in data))

    def tool(self, raw=False):
        return tools.body(StateReader(self.st), NOW, TODAY, raw=raw, env=self.env, home=self.root)

    def week(self):
        return jobs_runner.week_body(self.st, self.env, self.root, TODAY)

    def old_trend(self, rows):
        return body.trend(rows, TODAY, flat=body.flat_points(self.env, self.root))


class Config(Base):
    def test_defaults(self):
        self.assertEqual(bc.mode(self.env, self.root), "on")
        self.assertEqual(bc.reference_methods(self.env, self.root), ["dxa"])
        self.assertEqual(bc.pair_days(self.env, self.root), 3)

    def test_set_and_junk(self):
        self.configure(body_calibration="off", body_reference_methods=["dxa", "synthetic-reference"],
                       body_pair_days=1)
        self.assertEqual(bc.mode(self.env, self.root), "off")
        self.assertEqual(bc.reference_methods(self.env, self.root), ["dxa", "synthetic-reference"])
        self.assertEqual(bc.pair_days(self.env, self.root), 1)
        self.configure(body_calibration="OFF")
        self.assertEqual(bc.mode(self.env, self.root), "off")
        for junk in ({"body_calibration": "maybe"}, {"body_calibration": False}):
            self.configure(**junk)
            self.assertEqual(bc.mode(self.env, self.root), "on")
        for junk in ("dxa", [], [3], None):
            self.configure(body_reference_methods=junk)
            self.assertEqual(bc.reference_methods(self.env, self.root), ["dxa"], junk)
        for junk in (-1, 1.5, True, "3", None):
            self.configure(body_pair_days=junk)
            self.assertEqual(bc.pair_days(self.env, self.root), 3, junk)


class Trend(Base):
    def test_a_fit_feeds_the_trend_calibrated_rows(self):
        t = bc.trend(with_refs(), TODAY, self.env, self.root)
        self.assertEqual((t["direction"], t["modality"]), ("down", "measured"))
        self.assertEqual(t["label"], {"label": FITTED_DOWN, "tier": "T1", "modality": "measured"})
        self.assertEqual(t["calibration"], {"label": bc.FITTED, "tier": "T1"})
        # each scan ties between two scale days and takes the earlier: both differences are four points
        self.assertAlmostEqual(bc.fit(with_refs())["offset"], 4.0)
        self.assertAlmostEqual(t["prior"]["median"], 22.0)       # scale rows lifted beside the scan
        self.assertEqual(bc.review_line(t), "Body fat trending down (calibrated against reference scans).")

    def test_one_reference_scan_is_uncalibrated_in_words(self):
        rows = with_refs(1)
        t = bc.trend(rows, TODAY, self.env, self.root)
        self.assertEqual(t["label"], self.old_trend(rows)["label"])
        self.assertEqual(t["label"]["label"], "body fat trending down (uncalibrated estimate)")
        self.assertEqual(t["calibration"], {"label": bc.NO_FIT, "tier": "T1"})
        self.assertEqual(bc.review_line(t), "Body fat trending down (uncalibrated estimate). " + NO_FIT_SENTENCE)

    def test_no_reference_row_is_todays_trend_with_no_calibration_word(self):
        for rows in (scale_rows(), [dict(r, calibrated=True) for r in scale_rows()], scale_rows()[:2], []):
            t = bc.trend(rows, TODAY, self.env, self.root)
            self.assertEqual(t, self.old_trend(rows))
            self.assertEqual(bc.review_line(t), body.review_line(self.old_trend(rows)))

    def test_off_is_exactly_the_old_behaviour(self):
        self.configure(body_calibration="off")
        for rows in (with_refs(), with_refs(1), scale_rows(), []):
            self.assertEqual(bc.trend(rows, TODAY, self.env, self.root), self.old_trend(rows))
            self.assertEqual(bc.review_line(bc.trend(rows, TODAY, self.env, self.root)),
                             body.review_line(self.old_trend(rows)))

    def test_not_enough_measurements_with_a_fit_says_only_that(self):
        rows = thin_recent()
        self.assertEqual(bc.fit(rows)["model"], "offset")
        t = bc.trend(rows, TODAY, self.env, self.root)
        self.assertEqual(t["label"]["label"], body.NOT_ENOUGH)
        self.assertEqual(bc.review_line(t), "Body fat: not enough measurements.")


class ToolAndReview(Base):
    def test_the_tool_reads_calibrated_rows_when_a_fit_exists(self):
        self.write(with_refs())
        out = self.tool()
        self.assertEqual(out["value"], {"recent_rows": 4, "prior_rows": 4, "label": FITTED_DOWN,
                                        "calibration": bc.FITTED})
        self.assertEqual(out["modality"], "measured")
        self.assertEqual(out["label"]["label"], FITTED_DOWN)
        self.assertEqual(out["calibration"], {"label": bc.FITTED, "tier": "T1"})
        self.assertEqual(self.week(), "Body fat trending down (calibrated against reference scans).")

    def test_the_raw_opt_in_shows_trend_medians_never_the_fit(self):
        self.write(with_refs())
        value = self.tool(raw=True)["value"]
        self.assertEqual(set(value), {"recent_rows", "prior_rows", "label", "calibration", "recent_median",
                                      "prior_median", "change"})
        self.assertEqual(value["prior_median"], 22.0)

    def test_off_in_the_tool_and_the_review_is_the_old_output(self):
        self.write(with_refs())
        self.configure(body_calibration="off")
        out = self.tool()
        old = self.old_trend(StateReader(self.st).body_rows(self.env, self.root, today=TODAY))
        self.assertEqual(out["value"], {"recent_rows": 4, "prior_rows": 4, "label": old["label"]["label"]})
        self.assertEqual(out["label"], old["label"])
        self.assertNotIn("calibration", out)
        self.assertEqual(self.week(), body.review_line(old))
        self.assertEqual(self.week(), "Body fat trending down (uncalibrated estimate).")

    def test_one_scan_in_the_tool_and_the_review(self):
        self.write(with_refs(1))
        out = self.tool()
        self.assertEqual(out["value"]["calibration"], bc.NO_FIT)
        self.assertEqual(out["modality"], "proxy")
        self.assertEqual(self.week(), "Body fat trending down (uncalibrated estimate). " + NO_FIT_SENTENCE)


class DigitFree(Base):
    def test_every_calibration_word_and_label_has_no_digit(self):
        for w in bc.WORDS + body.LABELS:
            self.assertEqual(re.findall(r"\d", w), [], w)

    def test_results_and_review_lines_have_no_digit_outside_counts(self):
        for rows in (with_refs(), with_refs(1), scale_rows(), thin_recent()):
            self.write(rows)
            out = self.tool()
            for lab in tier_audit.labels(out):
                self.assertFalse(has_digit(lab), lab)
            v = dict(out["value"], recent_rows=None, prior_rows=None)
            self.assertFalse(has_digit(v), v)
            self.assertFalse(has_digit(self.week()), self.week())
            t = bc.trend(rows, TODAY, self.env, self.root)
            self.assertFalse(has_digit(t["label"]["label"]))            # the words; "T1" is the tier name
            self.assertFalse(has_digit((t.get("calibration") or {}).get("label")))


if __name__ == "__main__":
    unittest.main()
