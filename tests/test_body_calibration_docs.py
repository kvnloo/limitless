"""docs/body-calibration.md: the rules are named, the README links it, and its example output is real."""
import json
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import body_calibration as bc, jobs_runner, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

DOC = ROOT / "docs" / "body-calibration.md"
TODAY = date(2030, 1, 28)
NOW = datetime.combine(TODAY, time(12)).timestamp()


def row(ago, bf, method="synthetic-scale", cal=False):
    return {"day": (TODAY - timedelta(days=ago)).isoformat(), "bf_pct": bf, "method": method, "calibrated": cal}


SCALE = [row(27, 18.0), row(25, 18.2), row(23, 17.9), row(13, 17.0), row(11, 17.1), row(9, 16.9)]
REFS = [row(26, 22.0, "dxa", True), row(12, 21.0, "dxa", True)]


class Doc(unittest.TestCase):
    def test_it_names_the_config_and_the_rules(self):
        text = DOC.read_text()
        for word in ("body_reference_methods", "body_pair_days", "body_calibration", "calibrated_rows",
                     "earlier day", "five or more pairs", "leave-one-out", bc.NO_FIT, bc.FITTED):
            self.assertIn(word, text)

    def test_the_readme_links_it(self):
        self.assertIn("(docs/body-calibration.md)", (ROOT / "README.md").read_text())
        self.assertIn("body-calibration.md", (ROOT / "docs" / "body-trend.md").read_text())

    def test_the_example_output_is_what_the_code_prints(self):
        text = DOC.read_text()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            st = root / "state"
            st.mkdir()
            cfg = root / "config.json"
            env = {"LIMITLESS_CONFIG": str(cfg)}
            for name, rows, extra in (("two scans", SCALE + REFS, {}), ("one scan", SCALE + REFS[:1], {}),
                                      ("off", SCALE + REFS, {"body_calibration": "off"})):
                rows = sorted(rows, key=lambda r: r["day"])
                cfg.write_text(json.dumps(dict({"body_file": "body.jsonl"}, **extra)))
                (st / "body.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
                out = tools.body(StateReader(st), NOW, TODAY, env=env, home=root)
                self.assertIn(f"[{name}] limitless_body value: {json.dumps(out['value'])} modality: "
                              f"{out['modality']}", text)
                self.assertIn(f"[{name}] week review line: {jobs_runner.week_body(st, env, root, TODAY)}", text)
            for r in sorted(SCALE + REFS, key=lambda r: r["day"]):
                self.assertIn(json.dumps(r), text)
            f = bc.fit(SCALE + REFS)
            self.assertIn(str({k: f[k] for k in ("model", "pairs", "offset")}), text)

    def test_no_advice_words(self):
        text = DOC.read_text().lower()
        for bad in ("you should", "aim for", "goal of", "dose", "supplement"):
            self.assertNotIn(bad, text)
        self.assertEqual(re.findall(r"\b\d{1,2}:\d\d\b", text), [])     # no clock-time rule


if __name__ == "__main__":
    unittest.main()
