"""feed_reflex.label and its config: digit-free T1 words, thresholds as config (wording only)."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import feed_reflex  # noqa: E402


def got(n, k):
    return {"days": [], "unlocks": n, "feed_first": k, "newest": 1.0, "why": ""}


class Label(unittest.TestCase):
    def test_often_sometimes_rarely_by_share(self):
        self.assertEqual(feed_reflex.label(got(10, 6)), feed_reflex.OFTEN)
        self.assertEqual(feed_reflex.label(got(10, 5)), feed_reflex.OFTEN)
        self.assertEqual(feed_reflex.label(got(10, 3)), feed_reflex.SOMETIMES)
        self.assertEqual(feed_reflex.label(got(10, 2)), feed_reflex.SOMETIMES)
        self.assertEqual(feed_reflex.label(got(10, 1)), feed_reflex.RARELY)
        self.assertEqual(feed_reflex.label(got(10, 0)), feed_reflex.RARELY)

    def test_thresholds_change_the_wording_only(self):
        th = {"often": 0.9, "rarely": 0.05, "min_unlocks": 2}
        self.assertEqual(feed_reflex.label(got(10, 6), th), feed_reflex.SOMETIMES)
        self.assertEqual(feed_reflex.label(got(2, 0), th), feed_reflex.RARELY)

    def test_too_few_unlocks_is_unknown(self):
        self.assertEqual(feed_reflex.label(got(4, 4)), "unknown: " + feed_reflex.TOO_FEW)

    def test_unknown_says_why(self):
        u = {"days": [], "unlocks": None, "feed_first": None, "newest": None, "why": feed_reflex.NO_FEEDS}
        self.assertEqual(feed_reflex.label(u), "unknown: " + feed_reflex.NO_FEEDS)
        self.assertEqual(feed_reflex.label(None), "unknown: " + feed_reflex.NO_UNLOCKS)

    def test_is_often(self):
        self.assertTrue(feed_reflex.is_often(got(10, 6)))
        self.assertFalse(feed_reflex.is_often(got(10, 1)))
        self.assertFalse(feed_reflex.is_often(got(4, 4)))
        self.assertFalse(feed_reflex.is_often(None))

    def test_digit_walk_over_every_label_and_reason(self):
        texts = list(feed_reflex.WORDS) + list(feed_reflex.REASONS)
        texts += [feed_reflex.label(got(n, k)) for n in range(0, 30) for k in range(0, n + 1)]
        texts += ["unknown: " + w for w in feed_reflex.REASONS]
        texts += [feed_reflex.review_line(w) for w in feed_reflex.WORDS]
        for t in texts:
            self.assertNotRegex(t, r"\d", t)
            self.assertNotRegex(t.lower(), r"\b(streak|score|bad|fail|lazy|addict|should)\b", t)

    def test_review_line_only_for_a_known_word(self):
        self.assertEqual(feed_reflex.review_line(feed_reflex.OFTEN),
                         "Phone: a feed was often the first thing opened after unlocking this week.")
        self.assertEqual(feed_reflex.review_line("unknown: " + feed_reflex.NO_FEEDS), "")
        self.assertEqual(feed_reflex.review_line(None), "")


class Config(unittest.TestCase):
    def cfg(self, **kv):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = Path(tmp.name) / "config.json"
        p.write_text(json.dumps(kv))
        return {"LIMITLESS_CONFIG": str(p)}

    def test_defaults(self):
        env = self.cfg()
        self.assertEqual(feed_reflex.gap_s(env), feed_reflex.REFLEX_GAP_S)
        self.assertEqual(feed_reflex.thresholds(env), {"often": feed_reflex.OFTEN_SHARE,
                                                       "rarely": feed_reflex.RARELY_SHARE,
                                                       "min_unlocks": feed_reflex.MIN_UNLOCKS})

    def test_config_keys(self):
        env = self.cfg(feed_reflex_gap_s=45, feed_reflex_often_share=0.7, feed_reflex_rarely_share=0.1,
                       feed_reflex_min_unlocks=3)
        self.assertEqual(feed_reflex.gap_s(env), 45.0)
        self.assertEqual(feed_reflex.thresholds(env), {"often": 0.7, "rarely": 0.1, "min_unlocks": 3})

    def test_bad_values_fall_back(self):
        env = self.cfg(feed_reflex_gap_s="07:00", feed_reflex_often_share=2, feed_reflex_rarely_share=-1,
                       feed_reflex_min_unlocks=True)
        self.assertEqual(feed_reflex.gap_s(env), feed_reflex.REFLEX_GAP_S)
        th = feed_reflex.thresholds(env)
        self.assertEqual(th, {"often": feed_reflex.OFTEN_SHARE, "rarely": feed_reflex.RARELY_SHARE,
                              "min_unlocks": feed_reflex.MIN_UNLOCKS})

    def test_rarely_above_often_falls_back(self):
        env = self.cfg(feed_reflex_often_share=0.3, feed_reflex_rarely_share=0.6)
        th = feed_reflex.thresholds(env)
        self.assertEqual((th["often"], th["rarely"]), (feed_reflex.OFTEN_SHARE, feed_reflex.RARELY_SHARE))


if __name__ == "__main__":
    unittest.main()
