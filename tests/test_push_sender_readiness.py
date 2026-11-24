"""limitless.push_sender.readiness: whether kevin-push's sender profile can reach Telegram, from files only.

Beyond check (does the profile exist), readiness asks the profile's own files what ``hermes -p <profile> send
--to <target>`` would need: a Telegram bot token (``TELEGRAM_BOT_TOKEN`` in the profile's ``.env``, the
environment, or its ``config.yaml``) and a chat (a bare ``telegram`` target needs a home channel; a named target
needs a channel directory entry; a chat id is its own chat). Only presence is read: a token VALUE never leaves
the module. Synthetic Hermes homes and names only; no process is ever started.
"""
from hermetic_env import TEST_HOME, child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import push_sender as ps  # noqa: E402

READY = "ready"
NO_TOKEN = "no Telegram bot token in the sender profile"
NO_CHAT = "no Telegram chat set for the sender profile"
MISSING = "missing: the sender profile does not exist"
TOKEN = "SYNTHETICTOKENzz-value-never-shown"   # a made-up token value; it must never appear in any output


def no_process(*a, **k):
    raise AssertionError("readiness started a process")


class Home(unittest.TestCase):
    """A synthetic Hermes home: the root is the default profile, named profiles live under profiles/."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "hermes"
        (self.root / "profiles").mkdir(parents=True)
        for target in ((subprocess, "Popen"), (os, "fork"), (os, "posix_spawn"), (os, "system")):
            if hasattr(*target):
                p = mock.patch.object(*target, side_effect=no_process)
                p.start()
                self.addCleanup(p.stop)

    def profile(self, name, env_text=None, config_text=None):
        home = self.root if name == "default" else self.root / "profiles" / name
        home.mkdir(parents=True, exist_ok=True)
        if env_text is not None:
            (home / ".env").write_text(env_text)
        if config_text is not None:
            (home / "config.yaml").write_text(config_text)
        elif env_text is None and name != "default":
            (home / "config.yaml").write_text("")   # a Hermes identity marker: the dir is a live profile
        return home

    def ready(self, profile="sender-a", to="telegram", **env):
        cfg = {"push_profile": profile, "push_to": to}
        return ps.readiness(cfg, dict(env, HERMES_HOME=str(self.root)))


class Token(Home):
    def test_named_profile_with_token_and_home_channel_is_ready(self):
        self.profile("sender-a", f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_HOME_CHANNEL=12345\n")
        self.assertEqual(self.ready(), READY)

    def test_named_profile_without_env_file_has_no_token(self):
        self.profile("sender-a")
        self.assertEqual(self.ready(), NO_TOKEN)

    def test_a_blank_or_commented_token_is_no_token(self):
        for text in ("TELEGRAM_BOT_TOKEN=\n", "TELEGRAM_BOT_TOKEN=''\n", "# TELEGRAM_BOT_TOKEN=x\n",
                     "TELEGRAM_BOT_TOKEN=   # later\n", "OTHER_TOKEN=x\n"):
            self.profile("sender-a", text + "TELEGRAM_HOME_CHANNEL=12345\n")
            self.assertEqual(self.ready(), NO_TOKEN, text)

    def test_export_and_quotes_are_read_like_dotenv(self):
        for text in (f"export TELEGRAM_BOT_TOKEN={TOKEN}\n", f'TELEGRAM_BOT_TOKEN="{TOKEN}"\n',
                     f"TELEGRAM_BOT_TOKEN = '{TOKEN}'\n"):
            self.profile("sender-a", text + "TELEGRAM_HOME_CHANNEL=12345\n")
            self.assertEqual(self.ready(), READY, text)

    def test_the_token_from_the_environment_counts(self):
        self.profile("sender-a", "TELEGRAM_HOME_CHANNEL=12345\n")
        self.assertEqual(self.ready(TELEGRAM_BOT_TOKEN=TOKEN), READY)
        self.assertEqual(self.ready(TELEGRAM_BOT_TOKEN=" "), NO_TOKEN)

    def test_the_token_from_config_yaml_counts(self):
        for cfg in (f"TELEGRAM_BOT_TOKEN: {TOKEN}\n",
                    f"platforms:\n  telegram:\n    enabled: true\n    token: \"{TOKEN}\"\n"):
            self.profile("sender-a", "TELEGRAM_HOME_CHANNEL=12345\n", cfg)
            self.assertEqual(self.ready(), READY, cfg)

    def test_a_token_in_another_profile_does_not_count(self):
        self.profile("default", f"TELEGRAM_BOT_TOKEN={TOKEN}\n")
        self.profile("sender-b", f"TELEGRAM_BOT_TOKEN={TOKEN}\n")
        self.profile("sender-a", "TELEGRAM_HOME_CHANNEL=12345\n")
        self.assertEqual(self.ready(), NO_TOKEN)

    def test_a_secret_source_may_hold_the_token_so_it_is_unknown(self):
        self.profile("sender-a", "TELEGRAM_HOME_CHANNEL=12345\n", "secrets:\n  vault:\n    enabled: true\n")
        got = self.ready()
        self.assertTrue(got.startswith("unknown: "), got)

    def test_the_default_profile_reads_the_root_files(self):
        self.profile("default", f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_HOME_CHANNEL=12345\n")
        self.assertEqual(self.ready("default"), READY)
        self.assertEqual(ps.readiness({"push_profile": "default", "push_to": "telegram"},
                                      {"HERMES_HOME": str(self.root / "profiles" / "other")}), READY)
        (self.root / ".env").write_text("TELEGRAM_HOME_CHANNEL=12345\n")
        self.assertEqual(self.ready("default"), NO_TOKEN)


class Chat(Home):
    def setUp(self):
        super().setUp()
        self.env_line = f"TELEGRAM_BOT_TOKEN={TOKEN}\n"

    def test_a_bare_telegram_target_without_a_home_channel_has_no_chat(self):
        self.profile("sender-a", self.env_line)
        self.assertEqual(self.ready(), NO_CHAT)
        self.profile("sender-a", self.env_line + "TELEGRAM_HOME_CHANNEL=\n")
        self.assertEqual(self.ready(), NO_CHAT)

    def test_the_home_channel_from_env_or_config_counts(self):
        self.profile("sender-a", self.env_line)
        self.assertEqual(self.ready(TELEGRAM_HOME_CHANNEL="12345"), READY)
        self.profile("sender-a", self.env_line, "TELEGRAM_HOME_CHANNEL: '12345'\n")
        self.assertEqual(self.ready(), READY)
        self.profile("sender-a", self.env_line, "platforms:\n  telegram:\n    home_channel:\n"
                                                "      platform: telegram\n      chat_id: '12345'\n"
                                                "      name: Home\n")
        self.assertEqual(self.ready(), READY)

    def test_a_home_channel_for_another_platform_does_not_count(self):
        self.profile("sender-a", self.env_line + "DISCORD_HOME_CHANNEL=12345\n",
                     "platforms:\n  discord:\n    home_channel:\n      chat_id: '12345'\n")
        self.assertEqual(self.ready(), NO_CHAT)

    def test_a_chat_id_target_is_its_own_chat(self):
        self.profile("sender-a", self.env_line)
        for to in ("telegram:12345", "telegram:-100123", "telegram:12345:17", "telegram:@example_bot_user"):
            self.assertEqual(self.ready(to=to), READY, to)

    def test_a_named_target_needs_a_channel_directory_entry(self):
        home = self.profile("sender-a", self.env_line)
        self.assertEqual(self.ready(to="telegram:example-zz"), NO_CHAT)
        (home / "channel_directory.json").write_text(json.dumps(
            {"platforms": {"telegram": [{"id": "12345", "name": "Other-Person", "type": "dm"}]}}))
        self.assertEqual(self.ready(to="telegram:example-zz"), NO_CHAT)
        (home / "channel_directory.json").write_text(json.dumps(
            {"platforms": {"telegram": [{"id": "12345", "name": "Example-ZZ", "type": "dm"}]}}))
        self.assertEqual(self.ready(to="telegram:example-zz"), READY)

    def test_a_channel_alias_names_a_chat_too(self):
        home = self.profile("sender-a", self.env_line)
        (home / "channel_aliases.json").write_text(json.dumps({"telegram": {"12345": "example-zz"}}))
        self.assertEqual(self.ready(to="telegram:example-zz"), READY)

    def test_a_home_channel_does_not_resolve_a_named_target(self):
        self.profile("sender-a", self.env_line + "TELEGRAM_HOME_CHANNEL=12345\n")
        self.assertEqual(self.ready(to="telegram:example-zz"), NO_CHAT)

    def test_a_target_on_another_platform_is_unknown(self):
        self.profile("sender-a", self.env_line + "TELEGRAM_HOME_CHANNEL=12345\n")
        got = self.ready(to="discord:#ops")
        self.assertTrue(got.startswith("unknown: "), got)

    def test_the_token_is_asked_before_the_chat(self):
        self.profile("sender-a")
        self.assertEqual(self.ready(), NO_TOKEN)


class Existence(Home):
    def test_a_missing_profile_is_missing(self):
        self.assertEqual(self.ready(), MISSING)

    def test_check_unknowns_pass_through(self):
        got = ps.readiness({"push_profile": "sender-a"}, {"HERMES_HOME": str(self.root.parent / "nowhere")})
        self.assertEqual(got, ps.HOME_MISSING)
        self.assertEqual(ps.readiness({}, {}), ps.NO_HOME)

    def test_an_unreadable_profile_file_is_unknown(self):
        self.profile("sender-a", "TELEGRAM_BOT_TOKEN=x\n")
        with mock.patch.object(Path, "read_bytes", side_effect=PermissionError("no")):
            got = self.ready()
        self.assertTrue(got.startswith("unknown: "), got)

    def test_env_and_config_pick_the_profile_like_kevin_push(self):
        self.profile("sender-a", f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_HOME_CHANNEL=12345\n")
        env = {"HERMES_HOME": str(self.root), "KEVIN_PUSH_PROFILE": "sender-b"}
        self.assertEqual(ps.readiness({"push_profile": "sender-a", "push_to": "telegram"}, env), MISSING)
        env = {"HERMES_HOME": str(self.root), "KEVIN_PUSH_TO": "telegram:example-zz"}
        self.assertEqual(ps.readiness({"push_profile": "sender-a", "push_to": "telegram"}, env), NO_CHAT)


class Words(Home):
    def test_every_answer_is_one_of_the_states(self):
        self.assertEqual({ps.READY, ps.NO_TOKEN, ps.NO_CHAT, ps.MISSING}, {READY, NO_TOKEN, NO_CHAT, MISSING})

    def test_no_token_value_name_target_path_or_digit_in_any_answer(self):
        cases = [
            ("sender-zz", f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_HOME_CHANNEL=12345\n", None, "telegram"),
            ("sender-zz", f"TELEGRAM_BOT_TOKEN={TOKEN}\n", None, "telegram:example-zz"),
            ("sender-zz", "TELEGRAM_HOME_CHANNEL=12345\n", f"secrets:\n  v:\n    k: {TOKEN}\n", "telegram"),
            ("sender-zz", f"TELEGRAM_BOT_TOKEN={TOKEN}\n", None, "discord:example-zz"),
            ("sender-zz", "", None, "telegram"),
        ]
        got = []
        for name, env_text, cfg_text, to in cases:
            self.profile(name, env_text, cfg_text)
            got.append(self.ready(name, to, TELEGRAM_BOT_TOKEN=TOKEN + "-env"))
            got.append(self.ready(name, to))
        got.append(self.ready("sender-gone", "telegram:example-zz"))
        got.append(ps.readiness({"push_profile": "sender-zz"}, {"HERMES_HOME": str(self.root / "nowhere")}))
        for words in got:
            for leak in (TOKEN, "SYNTHETICTOKEN", "sender-zz", "sender-gone", "example-zz", str(self.root), "/",
                         str(TEST_HOME)):
                self.assertNotIn(leak, words)
            self.assertFalse(any(c.isdigit() for c in words), words)


class ReportOnly(unittest.TestCase):
    """kevin-push never asks readiness: a profile with no token or no chat still gets its send tried (a fake
    `hermes` on PATH records the call; nothing is sent), so a wrong readiness guess cannot block a real push."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        fakebin = self.home / "fakebin"
        fakebin.mkdir()
        hermes = fakebin / "hermes"
        hermes.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$HOME/hermes-calls\"\nexit 0\n")
        hermes.chmod(0o755)
        self.hermes_home = self.home / "hermes-home"
        (self.hermes_home / "profiles" / "sender-a").mkdir(parents=True)   # exists, but no .env at all
        (self.hermes_home / "profiles" / "sender-a" / "config.yaml").write_text("")   # a Hermes identity marker
        state = self.home / "state"
        state.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("KEVIN_PUSH_", "TELEGRAM_"))}
        self.env.update(HOME=str(self.home), PATH=f"{fakebin}:{os.environ['PATH']}",
                        HERMES_HOME=str(self.hermes_home), LIMITLESS_STATE=str(state),
                        LIMITLESS_CONFIG=str(self.home / "none.json"), KEVIN_PUSH_PROFILE="sender-a",
                        KEVIN_PUSH_TO="telegram", LIMITLESS_SLEEPMODE=str(state / "sleepmode.jsonl"),
                        CIRCADIAN_CLASS="decision")

    def test_no_token_still_tries_the_send(self):
        self.assertEqual(ps.readiness({}, self.env), NO_TOKEN)
        cli = Path(__file__).resolve().parents[1] / "bin" / "kevin-push"
        r = subprocess.run([sys.executable, "-I", str(cli), "x", "Pick one", "Keep the loop?"],
                           env=child_env(self.env), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.stdout.strip(), "kevin-push: telegram")
        calls = (self.home / "hermes-calls").read_text().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("-p sender-a send --to telegram"), calls[0])


if __name__ == "__main__":
    unittest.main()
