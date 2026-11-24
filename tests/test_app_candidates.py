"""app_candidates: the work and feed app lists proposed from observed app time, as one ready-to-send reply.

Synthetic rows only: well-known public app ids and names, and made-up app names; no real person's data.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import app_candidates as ac  # noqa: E402

NOW = 1894708800.0
M, H = 60.0, 3600.0
MADE_UP = ("zqnotes", "zqeditor", "zqscroller")


def row(start, minutes, *names, source=None):
    r = {"start": start, "end": start + minutes * M, "names": list(names)}
    if source:
        r["source"] = source
    return r


def week_rows():
    """Phone and desktop rows over a synthetic week: known feeds, known work apps, a browser, an unknown app."""
    t = NOW - 6 * 24 * H
    return [
        row(t, 90, "instagram", "com.instagram.android", source="phone"),
        row(t + 2 * H, 30, " Instagram", "com.instagram.android", source="phone"),   # same app, other case
        row(t + 3 * H, 60, " TikTok ", "com.zhiliaoapp.musically", source="phone"),
        row(t + 4 * H, 20, "reddit", "com.reddit.frontpage", source="phone"),
        row(t + 5 * H, 45, "zqnotes", "org.example.zqnotes", source="phone"),
        row(t + 6 * H, 240, "code", source="desktop"),
        row(t + 11 * H, 120, "gnome-terminal-server", source="desktop"),
        row(t + 14 * H, 300, "firefox", source="desktop"),                   # a browser: ambiguous, other
    ]


def names(entries):
    return [e["name"] for e in entries]


class Candidates(unittest.TestCase):
    def test_known_feed_and_work_apps_split_and_ranked_by_time(self):
        c = ac.candidates(week_rows())
        self.assertEqual(c["why"], "")
        self.assertEqual(names(c["feed"]), ["instagram", "tiktok", "reddit"])
        self.assertEqual(names(c["work"]), ["code", "gnome-terminal-server"])
        self.assertEqual(names(c["other"]), ["firefox", "zqnotes"])

    def test_package_id_and_display_name_are_one_app(self):
        c = ac.candidates(week_rows())
        insta = c["feed"][0]
        self.assertEqual(insta["seconds"], 120 * M)
        self.assertEqual(insta["names"], ["com.instagram.android", "instagram"])
        self.assertFalse(insta["kept"])

    def test_known_aliases_join_and_the_name_covering_most_time_wins(self):
        t = NOW - H   # rows that never carry both names: joined by the map, named so config matches most rows
        c = ac.candidates([row(t, 50, "com.zhiliaoapp.musically"), row(t + H / 2, 10, "TikTok")])
        self.assertEqual(c["feed"], [{"name": "com.zhiliaoapp.musically", "seconds": 60 * M, "kept": False,
                                      "names": ["com.zhiliaoapp.musically", "tiktok"]}])

    def test_names_are_trimmed_and_case_folded(self):
        t = NOW - H
        c = ac.candidates([row(t, 30, "  YouTube "), row(t + H / 2, 30, "youtube")])
        self.assertEqual(names(c["feed"]), ["youtube"])
        self.assertEqual(c["feed"][0]["seconds"], 60 * M)

    def test_app_or_package_keys_work_like_names(self):
        c = ac.candidates([{"start": NOW - H, "end": NOW, "app": "Reddit", "package": "com.reddit.frontpage"}])
        self.assertEqual(names(c["feed"]), ["reddit"])

    def test_top_n_per_list(self):
        t = NOW - 10 * H
        feeds = ["instagram", "tiktok", "reddit", "youtube", "facebook", "snapchat", "twitter"]
        rows = [row(t + i * H, 60 - i, f) for i, f in enumerate(feeds)]
        self.assertEqual(names(ac.candidates(rows)["feed"]), feeds[:5])
        self.assertEqual(names(ac.candidates(rows, max_n=2)["feed"]), feeds[:2])

    def test_config_lists_are_kept_never_dropped(self):
        t = NOW - 10 * H
        feeds = ["instagram", "tiktok", "reddit", "youtube", "facebook", "snapchat"]
        rows = [row(t + i * H, 60 - i, f) for i, f in enumerate(feeds)] + [row(t + 8 * H, 5, "zqscroller")]
        c = ac.candidates(rows, work_apps=["ZQEditor"], feed_apps=["zqscroller", "Snapchat"], max_n=2)
        self.assertEqual(names(c["feed"]), ["instagram", "tiktok", "Snapchat", "zqscroller"])
        self.assertEqual([e["kept"] for e in c["feed"]], [False, False, True, True])
        self.assertEqual(c["work"], [{"name": "ZQEditor", "seconds": 0.0, "kept": True, "names": []}])

    def test_a_config_list_beats_the_built_in_map(self):
        t = NOW - 2 * H
        c = ac.candidates([row(t, 60, "youtube"), row(t + H, 60, "code")], work_apps=["YouTube"])
        self.assertEqual(names(c["work"]), ["YouTube", "code"])
        self.assertEqual(c["feed"], [])

    def test_browsers_are_never_work_by_default(self):
        for b in ("firefox", "chrome", "google-chrome", "safari", "com.android.chrome", "org.mozilla.firefox"):
            self.assertEqual(ac.KNOWN.get(b, "other"), "other", b)
        c = ac.candidates([row(NOW - 2 * H, 100, "chrome"), row(NOW - H, 10, "code")])
        self.assertEqual(names(c["work"]), ["code"])

    def test_rows_outside_the_window_are_cut(self):
        rows = [row(NOW - 9 * 24 * H, 600, "instagram"), row(NOW - 2 * H, 60, "tiktok")]
        c = ac.candidates(rows, lo=NOW - 7 * 24 * H, hi=NOW)
        self.assertEqual(names(c["feed"]), ["tiktok"])

    def test_names_that_would_break_the_reply_are_left_out(self):
        rows = [row(NOW - 3 * H, 60, "a, b"), row(NOW - 2 * H, 60, "title:x"), row(NOW - H, 60, "code")]
        c = ac.candidates(rows)
        self.assertEqual(names(c["work"]), ["code"])
        self.assertEqual(c["other"], [])


class Unknown(unittest.TestCase):
    def check(self, c, why):
        self.assertEqual(c["why"], why)
        self.assertIsNone(c["work"])
        self.assertIsNone(c["feed"])
        self.assertEqual(ac.reply_line(c), "")
        self.assertEqual(ac.label(c), "unknown: " + why)

    def test_no_rows_is_unknown_never_empty_lists(self):
        self.check(ac.candidates(None), ac.NO_ROWS)
        self.check(ac.candidates([]), ac.NO_ROWS)
        self.check(ac.candidates([], work_apps=["code"], feed_apps=["reddit"]), ac.NO_ROWS)

    def test_too_little_activity_is_unknown(self):
        self.check(ac.candidates([row(NOW - H, 5, "instagram"), row(NOW - H / 2, 5, "code")]), ac.TOO_LITTLE)

    def test_no_known_app_is_unknown(self):
        self.check(ac.candidates([row(NOW - 3 * H, 120, "zqnotes")]), ac.NO_KNOWN)

    def test_bad_rows_are_skipped(self):
        rows = [None, {"start": "x", "end": 3}, {"start": NOW, "end": NOW - 1, "names": ["code"]}, row(NOW - H, 1)]
        self.check(ac.candidates(rows), ac.NO_ROWS)


class Reply(unittest.TestCase):
    def test_the_reply_is_two_lines_ready_to_send(self):
        c = ac.candidates(week_rows())
        self.assertEqual(ac.reply_line(c), "work apps: code, gnome-terminal-server\nfeed apps: instagram, tiktok, reddit")

    def test_one_list_is_one_line(self):
        c = ac.candidates([row(NOW - 2 * H, 60, "instagram")])
        self.assertEqual(ac.reply_line(c), "feed apps: instagram")
        self.assertEqual(ac.label(c), ac.FEED_ONLY)
        c = ac.candidates([row(NOW - 2 * H, 60, "code")])
        self.assertEqual(ac.reply_line(c), "work apps: code")
        self.assertEqual(ac.label(c), ac.WORK_ONLY)

    def test_the_label_is_digit_free_words_with_no_app_name(self):
        fixture_names = set(MADE_UP)
        for r in week_rows():
            fixture_names |= {n.strip().casefold() for n in r["names"]}
        cases = [ac.candidates(week_rows()), ac.candidates([]), ac.candidates([row(NOW - H, 1, "code")]),
                 ac.candidates([row(NOW - H, 60, "zqnotes")]), ac.candidates(week_rows(), work_apps=["zqeditor"])]
        for c in cases:
            lab = ac.label(c)
            self.assertNotRegex(lab, r"\d")
            for n in fixture_names:
                self.assertNotRegex(lab.casefold(), r"\b" + re.escape(n) + r"\b", (lab, n))
        self.assertEqual(ac.label(cases[0]), ac.BOTH)
        self.assertEqual(ac.BOTH, "work and feed app lists proposed")
        for w in ac.WORDS + ac.REASONS:
            self.assertNotRegex(w, r"\d")


if __name__ == "__main__":
    unittest.main()
