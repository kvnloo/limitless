"""ui_card.write: atomic, 0600, named by a content hash (no date or clock); card_dir from env or config."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import ui_card  # noqa: E402

HTML = ui_card.render("Today", ["window: peak (proxy)"], "state")["html"]


class Write(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "cards"

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_the_html_with_mode_0600(self):
        p = ui_card.write(self.dir, HTML)
        self.assertEqual(Path(p).read_text(encoding="utf-8"), HTML)
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertEqual(Path(p).parent, self.dir)

    def test_name_is_the_content_hash_with_no_date_or_clock(self):
        p = Path(ui_card.write(self.dir, HTML))
        self.assertRegex(p.name, r"^card-[0-9a-f]{16}\.html$")
        self.assertNotRegex(p.name, r"\d{4}-\d{2}|\d{2}:\d{2}|T\d{2}")
        with mock.patch("time.time", return_value=0.0):
            self.assertEqual(Path(ui_card.write(self.dir, HTML)), p)   # same content, same name, any time
        other = ui_card.render("Today", ["window: trough (proxy)"], "state")["html"]
        self.assertNotEqual(Path(ui_card.write(self.dir, other)), p)

    def test_atomic_no_partial_file_and_no_temp_left(self):
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                ui_card.write(self.dir, HTML)
        self.assertEqual(sorted(os.listdir(self.dir)), [])

    def test_no_dir_writes_nothing(self):
        self.assertIsNone(ui_card.write(None, HTML))
        self.assertIsNone(ui_card.write("", HTML))
        self.assertFalse(self.dir.exists())


class CardDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_env_wins_then_config_then_unset(self):
        cfg = self.home / "config.json"
        cfg.write_text(json.dumps({"card_dir": str(self.home / "from-config")}))
        env = {"LIMITLESS_CONFIG": str(cfg)}
        self.assertEqual(ui_card.card_dir(env, self.home), self.home / "from-config")
        env["LIMITLESS_CARD_DIR"] = str(self.home / "from-env")
        self.assertEqual(ui_card.card_dir(env, self.home), self.home / "from-env")
        self.assertIsNone(ui_card.card_dir({}, self.home))

    def test_unset_says_why_in_words(self):
        self.assertIn("LIMITLESS_CARD_DIR", ui_card.NO_DIR)
        self.assertIn("card_dir", ui_card.NO_DIR)
        self.assertNotRegex(ui_card.NO_DIR, r"\d|/")


if __name__ == "__main__":
    unittest.main()
