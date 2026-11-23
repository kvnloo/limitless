"""flow_ledger.label: the day's ledger in plain, digit-free words, through tier_audit.gate. No score, no advice."""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from limitless import flow_ledger, tier_audit  # noqa: E402
from test_flow_ledger import DS, items, ledger, long_block  # noqa: E402

H = 3600.0


def got(long_blocks, leaks, landed=None):
    return {"day": "2033-05-17", "blocks": [], "long_blocks": long_blocks, "leaks": leaks, "landed": landed, "why": ""}


class Words(unittest.TestCase):
    def test_the_brief_example(self):
        self.assertEqual(flow_ledger.label(got(2, 1, 3)), "two long blocks, one with a feed leak; three items landed")

    def test_no_long_blocks(self):
        self.assertEqual(flow_ledger.label(got(0, 0)), "no long blocks")
        self.assertEqual(flow_ledger.label(got(0, 0, 1)), "no long blocks; one item landed")
        self.assertEqual(flow_ledger.label(got(0, None, 0)), "no long blocks; nothing landed")

    def test_leak_wording(self):
        cases = {(1, 0): "one long block, no feed leak", (1, 1): "one long block, with a feed leak",
                 (2, 0): "two long blocks, none with a feed leak", (2, 2): "two long blocks, both with a feed leak",
                 (3, 3): "three long blocks, all with a feed leak", (4, 2): "four long blocks, two with a feed leak",
                 (2, None): "two long blocks, feed leaks unknown"}
        for (n, k), want in cases.items():
            self.assertEqual(flow_ledger.label(got(n, k)), want)

    def test_counts_are_spelled_and_several_above_ten(self):
        self.assertEqual(flow_ledger.label(got(10, 0)), "ten long blocks, none with a feed leak")
        self.assertEqual(flow_ledger.label(got(11, 0, 12)), "several long blocks, none with a feed leak; several items landed")
        for n in range(0, 30):
            for k in (None, 0, n // 2, n):
                for landed in (None, 0, n):
                    self.assertEqual(re.findall(r"\d", flow_ledger.label(got(n, k, landed))), [])

    def test_unknown_says_why(self):
        self.assertEqual(flow_ledger.label(ledger(None)), "unknown: no app activity that day")
        self.assertEqual(flow_ledger.label(None), "unknown")

    def test_from_a_real_ledger(self):
        rows = long_block(DS + 9 * H) + long_block(DS + 13 * H, feed=True) + long_block(DS + 17 * H, minutes=20)
        word = flow_ledger.label(ledger(rows, its=items(("done", DS + 1), ("failed", DS + 2))))
        self.assertEqual(word, "two long blocks, one with a feed leak; one item landed")

    def test_no_clock_time_app_or_file_name_or_score_words(self):
        rows = long_block(DS + 9 * H, feed=True)
        word = flow_ledger.label(ledger(rows, its=items(("done", DS + 1))))
        for bad in ("editor", "org.example", "chat", "synthetic", ".md", ":", "score", "productiv", "should", "try",
                    "good", "bad", "great", "target", "goal", "%"):
            self.assertNotIn(bad, word)

    def test_t1_label_dict(self):
        self.assertEqual(flow_ledger.t1(got(0, 0)), {"label": "no long blocks", "tier": "T1", "modality": "observed"})

    def test_the_words_pass_the_tier_audit_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"LIMITLESS_AUDIT": str(Path(tmp) / "a.jsonl"), "LIMITLESS_CONFIG": str(Path(tmp) / "c.json")}
            word = flow_ledger.label(got(2, 1, 3))
            self.assertEqual(tier_audit.gate("brief:flow_ledger", word, False, env, Path(tmp)), word)


if __name__ == "__main__":
    unittest.main()
