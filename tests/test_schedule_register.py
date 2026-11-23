"""register(ctx) offers every schedule card to a host that can take them (feature detection), else does nothing."""
import logging
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_plugin import FakeCtx, load_plugin, manifest_list  # noqa: E402

from limitless import jobs, schedule_cards  # noqa: E402

METHOD = "register_schedule_card"


class CardCtx(FakeCtx):
    """A host with the schedule-card registration method."""

    def __init__(self):
        super().__init__()
        self.cards = []

    def register_schedule_card(self, card):
        self.cards.append(card)


class BrokenCardCtx(FakeCtx):
    def register_schedule_card(self, card):
        raise RuntimeError("host refused the card")


def _ours(cm):
    return [r for r in cm.records if r.name.endswith("limitless.plugin")]


class HostRegistration(unittest.TestCase):
    def register(self, ctx, env=None):
        with mock.patch.dict(os.environ, env or {}, clear=True), \
                self.assertLogs(level="DEBUG") as cm:
            logging.getLogger("limitless-schedule-test").debug("anchor")   # assertLogs needs one record
            load_plugin().register(ctx)
        return _ours(cm)

    def assert_rest_registered(self, ctx):
        self.assertEqual(sorted(ctx.tools), sorted(manifest_list("provides_tools")))
        self.assertEqual(sorted(ctx.hooks), sorted(manifest_list("provides_hooks")))

    def test_the_method_name_is_the_documented_one(self):
        self.assertEqual(schedule_cards.HOST_METHOD, METHOD)

    def test_a_host_with_the_method_gets_every_card(self):
        ctx = CardCtx()
        self.register(ctx)
        self.assertEqual(ctx.cards, schedule_cards.cards())
        self.assertEqual([c["id"] for c in ctx.cards], list(jobs.SPECS))
        self.assert_rest_registered(ctx)

    def test_external_jobs_reach_the_host_as_external(self):
        ctx = CardCtx()
        self.register(ctx, {"LIMITLESS_EXTERNAL_JOBS": "miq"})
        self.assertEqual({c["id"]: c["sender"] for c in ctx.cards}["miq"], "external")

    def test_a_host_without_it_gets_nothing_and_one_content_free_line(self):
        ctx = FakeCtx()
        self.assertFalse(hasattr(ctx, METHOD))
        lines = self.register(ctx)
        self.assertEqual(len(lines), 1, [r.getMessage() for r in lines])
        msg = lines[0].getMessage()
        self.assertEqual(msg, schedule_cards.NO_HOST)
        self.assertFalse(any(c.isdigit() for c in msg))
        for c in schedule_cards.cards():
            self.assertNotIn(c["name"], msg)
            self.assertNotIn(c["id"], msg)
        self.assert_rest_registered(ctx)

    def test_a_non_callable_attribute_counts_as_absent(self):
        ctx = FakeCtx()
        ctx.register_schedule_card = None
        lines = self.register(ctx)
        self.assertEqual([r.getMessage() for r in lines], [schedule_cards.NO_HOST])
        self.assert_rest_registered(ctx)

    def test_a_host_that_raises_never_fails_register(self):
        ctx = BrokenCardCtx()
        lines = self.register(ctx)
        self.assertEqual([r.getMessage() for r in lines], [schedule_cards.HOST_FAILED])
        self.assertNotIn("refused", schedule_cards.HOST_FAILED)
        self.assert_rest_registered(ctx)


if __name__ == "__main__":
    unittest.main()
