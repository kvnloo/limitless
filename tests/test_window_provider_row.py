"""The doctor's `cron window provider` row: off in config, a Hermes with no hook, or live with the window now.

Synthetic fixtures only: a tiny fake hermes_cli/plugins_context.py in a temp dir stands in for the Hermes source
checkout (config hermes_agent_dir); Hermes itself is never imported or run.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import decision_window, doctor, window_provider  # noqa: E402

NOW = 1894708800.0   # the fixture clock; the row reads events, never this hour
ROW = "cron window provider"
OFF = "window_provider is off in config"
NO_HOOK = "this Hermes has no cron window provider hook"
NOT_CHECKED = "host support not checked (set hermes_agent_dir); the window now is "
HOLD = "none, so windowed jobs hold"
WITHOUT = "class PluginContext:\n    def register_tool(self, name, schema, handler):\n        pass\n"
WITH = WITHOUT + "\n    def register_window_provider(self, provider):\n        self.provider = provider\n"


def reads(word):
    return lambda now: word


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        p = mock.patch.dict(os.environ, {}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def hermes(self, source=WITHOUT, name="hermes-agent"):
        """A fake Hermes checkout: <root>/<name>/hermes_cli/plugins_context.py holding ``source``."""
        d = self.root / name
        (d / "hermes_cli").mkdir(parents=True)
        (d / "hermes_cli" / "plugins_context.py").write_text(source)
        return d

    def row(self, cfg=None, word="trough"):
        return doctor.cron_window_provider_row({} if cfg is None else cfg, NOW, read=reads(word))

    def check(self, r, status, reason):
        self.assertEqual((r["name"], r["kind"], r["status"], r["reason"]), (ROW, "source", status, reason))
        self.assertEqual(doctor.text([r]), f"{ROW}: {status}: {reason}")


class Off(Case):
    def test_off_in_config_says_so_whatever_the_host(self):
        for v in (False, "off", "OFF", "false"):
            self.check(self.row({"window_provider": v}), doctor.OFF, OFF)
            self.check(self.row({"window_provider": v, "hermes_agent_dir": str(self.hermes(WITH, f"h{id(v)}"))}),
                       doctor.OFF, OFF)

    def test_on_by_default_follows_window_provider_enabled(self):
        for cfg in ({}, {"window_provider": True}, {"window_provider": "on"}):
            self.assertTrue(window_provider.enabled(cfg))
            self.assertEqual(self.row(cfg)["status"], doctor.LIVE)


class Host(Case):
    def test_a_hermes_without_the_method_is_missing(self):
        self.check(self.row({"hermes_agent_dir": str(self.hermes(WITHOUT))}), doctor.MISSING, NO_HOOK)

    def test_a_hermes_with_the_method_is_live_with_the_window_now(self):
        self.check(self.row({"hermes_agent_dir": str(self.hermes(WITH))}), doctor.LIVE, "the window now is trough")

    def test_the_row_changes_when_the_fake_file_gains_the_method(self):
        d = self.hermes(WITHOUT)
        before = self.row({"hermes_agent_dir": str(d)})
        with open(d / "hermes_cli" / "plugins_context.py", "a") as f:
            f.write("\n    def register_window_provider(self, provider):\n        pass\n")
        after = self.row({"hermes_agent_dir": str(d)})
        self.assertNotEqual(before, after)
        self.assertEqual((before["status"], after["status"]), (doctor.MISSING, doctor.LIVE))

    def test_a_commented_or_longer_name_is_not_the_hook(self):
        for src in (WITHOUT + "    # def register_window_provider(self, provider):\n",
                    WITHOUT + "    def register_window_provider_later(self, provider):\n        pass\n",
                    WITHOUT + "    register_window_provider = None\n"):
            d = self.hermes(src, f"h{abs(hash(src))}")
            self.check(self.row({"hermes_agent_dir": str(d)}), doctor.MISSING, NO_HOOK)

    def test_a_tilde_path_is_expanded(self):
        self.hermes(WITH)
        os.environ["HOME"] = str(self.root)
        self.check(self.row({"hermes_agent_dir": "~/hermes-agent"}), doctor.LIVE, "the window now is trough")

    def test_hermes_is_never_imported(self):
        d = self.hermes(WITH + "\nraise SystemExit('imported')\n")
        before = set(sys.modules)
        self.check(self.row({"hermes_agent_dir": str(d)}), doctor.LIVE, "the window now is trough")
        self.assertFalse({m for m in set(sys.modules) - before if "hermes" in m or "plugins_context" in m})


class NotChecked(Case):
    def test_unset_key_is_live_and_says_host_support_was_not_checked(self):
        self.check(self.row({}), doctor.LIVE, NOT_CHECKED + "trough")
        self.check(self.row({"hermes_agent_dir": ""}), doctor.LIVE, NOT_CHECKED + "trough")
        self.check(self.row({"hermes_agent_dir": None}), doctor.LIVE, NOT_CHECKED + "trough")

    def test_an_unreadable_dir_is_not_checked(self):
        for value in (str(self.root / "gone"), str(self.root / "a-file"), str(self.root / "empty"), ["a", "list"]):
            (self.root / "a-file").write_text("not a dir")
            (self.root / "empty").mkdir(exist_ok=True)
            self.check(self.row({"hermes_agent_dir": value}), doctor.LIVE, NOT_CHECKED + "trough")

    def test_a_file_that_cannot_be_opened_is_not_checked(self):
        d = self.hermes(WITH)
        with mock.patch("builtins.open", side_effect=PermissionError("denied")):
            r = self.row({"hermes_agent_dir": str(d)})
        self.check(r, doctor.LIVE, NOT_CHECKED + "trough")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads a mode-000 dir")
    def test_a_mode_000_dir_is_not_checked(self):
        d = self.hermes(WITH)
        os.chmod(d / "hermes_cli", 0)
        self.addCleanup(os.chmod, d / "hermes_cli", 0o755)
        self.check(self.row({"hermes_agent_dir": str(d)}), doctor.LIVE, NOT_CHECKED + "trough")


class Words(Case):
    def test_each_window_word_maps_through_to_cron(self):
        d = str(self.hermes(WITH))
        for word, said in (("peak", "peak"), ("trough", "trough"), ("anytime", "anytime"),
                           ("wind_down", "wind_down"), ("asleep", HOLD), ("focus_block", HOLD),
                           (decision_window.UNKNOWN, HOLD), ("not-a-word", HOLD)):
            self.assertEqual(window_provider.TO_CRON.get(word), None if said == HOLD else said)
            self.check(self.row({"hermes_agent_dir": d}, word), doctor.LIVE, f"the window now is {said}")
            self.check(self.row({}, word), doctor.LIVE, NOT_CHECKED + said)

    def test_a_reader_that_raises_holds_and_the_row_never_raises(self):
        def boom(now):
            raise RuntimeError("a broken reader at /made/up/path 42")
        r = doctor.cron_window_provider_row({}, NOW, read=boom)
        self.check(r, doctor.LIVE, NOT_CHECKED + HOLD)
        r = doctor.cron_window_provider_row("not a dict", NOW, read=reads("peak"))
        self.assertEqual(r["status"], doctor.LIVE)

    def test_no_digit_and_no_path_in_any_row(self):
        d = self.hermes(WITH, "hermes-agent-2030")
        bare = self.hermes(WITHOUT, "hermes-agent-1999")
        cfgs = ({}, {"window_provider": False}, {"hermes_agent_dir": str(d)}, {"hermes_agent_dir": str(bare)},
                {"hermes_agent_dir": str(self.root / "gone-123")})
        for cfg in cfgs:
            for word in list(window_provider.TO_CRON) + ["?"]:
                line = doctor.text([self.row(cfg, word)])
                self.assertNotRegex(line, r"\d", line)
                self.assertNotIn("/", line)
                self.assertNotIn(str(self.root), line)


class DefaultReader(Case):
    def test_without_a_reader_it_reads_the_window_from_the_configured_state_dir(self):
        st = self.root / "state"
        st.mkdir()
        (st / "sleepmode.jsonl").write_text(json.dumps({"at": NOW - 3600, "on": True}) + "\n")
        (st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
        r = doctor.cron_window_provider_row({"state": str(st)}, NOW)
        self.check(r, doctor.LIVE, NOT_CHECKED + HOLD)   # asleep holds every windowed job


class InTheReport(Case):
    def test_the_report_has_it_once_right_after_the_noop_mcp_row(self):
        os.environ["LIMITLESS_STATE"] = str(self.root)
        rows = doctor.report({"state": str(self.root)}, NOW)
        names = [r["name"] for r in rows]
        self.assertEqual(names.count(ROW), 1)
        at = names.index(ROW)
        self.assertEqual(names[at - 1], doctor.NOOP_MCP_ROW)
        self.assertEqual(names[at + 1], doctor.HOST_SCRIPTS_ROW)   # then the host job scripts row
        self.assertEqual(names[at + 2], doctor.DESKTOP_AW_ROW)
        self.assertEqual(rows[at]["kind"], "source")
        self.assertNotIn("source", doctor.STRICT_KINDS)
        self.assertEqual((rows[at]["status"], rows[at]["reason"]), (doctor.LIVE, NOT_CHECKED + HOLD))


if __name__ == "__main__":
    unittest.main()
