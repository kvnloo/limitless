"""register(ctx) offers Hermes' cron gate the plugin's decision window (limitless/window_provider.py)."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import logging
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_plugin import FakeCtx, fake_ctx_hooks, load_plugin, manifest_list  # noqa: E402

from limitless import decision_window, window, window_provider  # noqa: E402

# The host's WindowClass values, copied from the fork that adds the cron gate:
# kvnloo/hermes-agent up/cron-decision-window-gate-r2 (a910662), cron/decision_window.py lines 30-34.
# The gate (same file, lines 128-148) reads None as "window unknown" and holds every windowed job.
HERMES_WINDOW_CLASSES = frozenset({"peak", "trough", "anytime", "wind_down"})
METHOD = "register_window_provider"

NOW = datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc)   # synthetic; the provider reads events, not this hour
T = NOW.timestamp()


class ProviderCtx(FakeCtx):
    """A host with the fork's register_window_provider."""

    def __init__(self):
        super().__init__()
        self.providers = []

    def register_window_provider(self, provider):
        self.providers.append(provider)


class BrokenProviderCtx(FakeCtx):
    def register_window_provider(self, provider):
        raise TypeError("host refused the provider")


def _rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class Fixture:
    """A synthetic state dir (and optional Glide attention file) for one plugin window state."""

    def __init__(self, test):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.cfg = self.root / "config.json"
        self.cfg.write_text(json.dumps({"state": str(self.state)}))
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}

    def awake_since(self, hours):
        _rows(self.state / "sleepmode.jsonl", [{"at": T - hours * 3600 - 8 * 3600, "on": True},
                                               {"at": T - hours * 3600, "on": False}])
        (self.state / "sleepmode-poll.json").write_text(json.dumps({"at": T - 60, "ok": True}))
        return self

    def asleep(self):
        _rows(self.state / "sleepmode.jsonl", [{"at": T - 3600, "on": True}])
        (self.state / "sleepmode-poll.json").write_text(json.dumps({"at": T - 60, "ok": True}))
        return self

    def glide(self, data):
        path = self.root / "attention.json"
        path.write_text(json.dumps(data))
        self.env["LIMITLESS_GLIDE_ATTENTION"] = str(path)
        return self

    def mode(self, name):
        (self.state / "mode.json").write_text(json.dumps({"mode": name}))
        return self

    def current(self):
        with mock.patch.dict(os.environ, self.env, clear=True):
            return window_provider.WindowProvider().current(NOW)


class Mapping(unittest.TestCase):
    def test_the_table_covers_every_window_word_the_plugin_produces(self):
        words = (set(window.CLASSES) | set(decision_window.WINDOW_CLASSES)
                 | {decision_window.UNKNOWN, window_provider.FOCUS_BLOCK})
        unmapped = sorted(words - set(window_provider.TO_CRON))
        self.assertEqual(unmapped, [], f"window words with no cron mapping: {unmapped}")

    def test_the_table_maps_only_to_the_hosts_classes_or_none(self):
        outside = {w: v for w, v in window_provider.TO_CRON.items()
                   if v is not None and v not in HERMES_WINDOW_CLASSES}
        self.assertEqual(outside, {})

    def test_every_open_class_maps_to_itself_and_closed_states_to_none(self):
        for cls in decision_window.WINDOW_CLASSES:
            self.assertEqual(window_provider.TO_CRON[cls], cls)
        for word in ("asleep", decision_window.UNKNOWN, window_provider.FOCUS_BLOCK):
            self.assertIsNone(window_provider.TO_CRON[word], word)


class Current(unittest.TestCase):
    """current(now) through the readers limitless_window uses, on synthetic state."""

    def check(self, fixture, expected):
        got = fixture.current()
        self.assertTrue(got is None or got in HERMES_WINDOW_CLASSES, got)
        self.assertEqual(got, expected)

    def test_peak(self):
        self.check(Fixture(self).awake_since(2), "peak")

    def test_trough(self):
        self.check(Fixture(self).awake_since(7), "trough")

    def test_anytime(self):
        self.check(Fixture(self).awake_since(10), "anytime")

    def test_wind_down_from_glide(self):
        self.check(Fixture(self).awake_since(10).glide({"wind_down": {"started": T - 600, "by": "nudge",
                                                                      "ended": None}}), "wind_down")

    def test_asleep_holds_every_windowed_job(self):
        self.check(Fixture(self).asleep(), None)

    def test_a_focus_block_holds_every_windowed_job(self):
        self.check(Fixture(self).awake_since(2).glide({"block": {"start": T - 600, "end": T + 600}}), None)

    def test_focused_mode_holds_like_a_focus_block(self):
        self.check(Fixture(self).awake_since(2).mode("focused"), None)

    def test_unknown_with_no_events(self):
        self.check(Fixture(self), None)

    def test_a_reader_that_raises_is_none(self):
        def boom(ts):
            raise RuntimeError("reader broke")
        self.assertIsNone(window_provider.WindowProvider(read=boom).current(NOW))

    def test_a_word_outside_the_table_is_none(self):
        self.assertIsNone(window_provider.WindowProvider(read=lambda ts: "lunch").current(NOW))

    def test_a_bad_now_is_none(self):
        self.assertIsNone(window_provider.WindowProvider(read=lambda ts: "peak").current("not a datetime"))

    def test_now_reaches_the_reader_as_epoch_seconds(self):
        seen = []
        window_provider.WindowProvider(read=lambda ts: seen.append(ts) or "peak").current(NOW)
        self.assertEqual(seen, [T])


def _ours(cm):
    return [r for r in cm.records if r.name.endswith("window_provider")]


class HostRegistration(unittest.TestCase):
    def register(self, ctx, cfg=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "config.json"
        if cfg is not None:
            path.write_text(json.dumps(cfg))
        with mock.patch.dict(os.environ, {"LIMITLESS_CONFIG": str(path)}, clear=True), \
                self.assertLogs(level="DEBUG") as cm:
            logging.getLogger("limitless-window-provider-test").debug("anchor")   # assertLogs needs one record
            load_plugin().register(ctx)
        return _ours(cm)

    def assert_rest_registered(self, ctx):
        self.assertEqual(sorted(ctx.tools), sorted(manifest_list("provides_tools")))
        self.assertEqual(sorted(ctx.hooks), fake_ctx_hooks())

    def test_the_method_name_is_the_hosts(self):
        self.assertEqual(window_provider.HOST_METHOD, METHOD)

    def test_a_host_without_the_method_gets_nothing_and_no_error(self):
        ctx = FakeCtx()
        self.assertFalse(hasattr(ctx, METHOD))
        lines = self.register(ctx)
        self.assertEqual([r.getMessage() for r in lines], [window_provider.NO_HOST])
        self.assert_rest_registered(ctx)

    def test_a_host_with_it_gets_one_provider(self):
        ctx = ProviderCtx()
        self.register(ctx)
        self.assertEqual(len(ctx.providers), 1)
        # load_plugin imports the package under a host name, so compare the class by name
        self.assertEqual(type(ctx.providers[0]).__name__, window_provider.WindowProvider.__name__)
        self.assertTrue(callable(ctx.providers[0].current))
        self.assert_rest_registered(ctx)

    def test_the_registered_provider_answers_with_a_host_class(self):
        ctx = ProviderCtx()
        self.register(ctx)
        f = Fixture(self).awake_since(2)
        with mock.patch.dict(os.environ, f.env, clear=True):
            self.assertEqual(ctx.providers[0].current(NOW), "peak")

    def test_off_registers_nothing(self):
        for off in ("off", False, "false", " OFF "):
            ctx = ProviderCtx()
            lines = self.register(ctx, {"window_provider": off})
            self.assertEqual(ctx.providers, [], off)
            self.assertEqual([r.getMessage() for r in lines], [window_provider.DISABLED])
            self.assert_rest_registered(ctx)

    def test_on_by_default_and_when_set_on(self):
        for cfg in (None, {}, {"window_provider": "on"}, {"window_provider": True}):
            ctx = ProviderCtx()
            self.register(ctx, cfg)
            self.assertEqual(len(ctx.providers), 1, cfg)

    def test_a_host_that_raises_gets_one_line_and_register_goes_on(self):
        ctx = BrokenProviderCtx()
        lines = self.register(ctx)
        self.assertEqual([r.getMessage() for r in lines], [window_provider.HOST_FAILED])
        self.assert_rest_registered(ctx)

    def test_log_lines_are_content_free(self):
        for line in (window_provider.NO_HOST, window_provider.DISABLED, window_provider.HOST_FAILED):
            self.assertFalse(any(c.isdigit() for c in line), line)


if __name__ == "__main__":
    unittest.main()
