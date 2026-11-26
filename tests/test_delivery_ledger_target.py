"""limitless/delivery_ledger.ledger_target: kevin-push's send target (``hermes send --to``) as the ledger's
``platform:chat_id:thread_id`` budget key.

Synthetic targets only; nothing is resolved, sent or read from state.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import delivery_ledger as dl  # noqa: E402
from limitless import push_sender  # noqa: E402


class LedgerTargetCase(unittest.TestCase):
    def test_contact_alias_gets_an_empty_thread(self):
        self.assertEqual(dl.ledger_target("telegram:example-contact"), "telegram:example-contact:")

    def test_default_send_target_maps_to_a_key_the_ledger_accepts(self):
        key = dl.ledger_target(push_sender.TARGET_DEFAULT)
        self.assertTrue(dl._target_ok(key))
        self.assertEqual(key.count(":"), 2)

    def test_chat_and_topic_stay_as_chat_and_thread(self):
        self.assertEqual(dl.ledger_target("telegram:-1001234:77"), "telegram:-1001234:77")

    def test_bare_platform_is_its_home_channel(self):
        self.assertEqual(dl.ledger_target("telegram"), "telegram:" + dl.HOME_CHAT + ":")
        self.assertEqual(dl.ledger_target("telegram:"), "telegram:" + dl.HOME_CHAT + ":")

    def test_platform_case_and_spaces_do_not_split_the_budget(self):
        self.assertEqual(dl.ledger_target("  Telegram : example-contact "), "telegram:example-contact:")

    def test_the_same_target_always_gives_the_same_key(self):
        self.assertEqual(dl.ledger_target("telegram:example-contact"), dl.ledger_target("telegram:example-contact"))

    def test_different_contacts_get_different_keys(self):
        self.assertNotEqual(dl.ledger_target("telegram:contact-a"), dl.ledger_target("telegram:contact-b"))

    def test_bad_targets_raise(self):
        for bad in ("", "   ", ":example-contact", "telegram:a\nb", None, 7):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    dl.ledger_target(bad)

    def test_key_reserves_and_counts_in_the_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = dl.open_ledger(Path(tmp) / "ledger.sqlite3")
            try:
                key = dl.ledger_target("telegram:example-contact")
                dl.reserve(conn, key, "synthetic body", day_start=0.0, now=10.0)
                self.assertEqual(dl.used(conn, key, 0.0), 1)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
