"""The synthetic push sender example in docs/doctor.md: python3 -I scripts/push_sender_readiness_example.py

A made-up Hermes home in a temp dir with a few made-up sender profiles (a made-up bot token, a made-up home
channel id, a made-up channel directory), and limitless-doctor's real "push sender" row (doctor.push_sender_row,
which asks push_sender.readiness) for each pick of sender. Files only: it never runs hermes, never sends and
reads no real state. The token value is never printed: only whether it is there.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import doctor  # noqa: E402

TOKEN = "made-up-token-never-printed"
HOME_CHANNEL = "100001"   # a made-up home channel id

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / "hermes"

    def sender(name, env_lines=(), files=None):
        home = root / "profiles" / name
        home.mkdir(parents=True)
        if env_lines:
            (home / ".env").write_text("".join(f"{line}\n" for line in env_lines))
        for fname, data in (files or {}).items():
            (home / fname).write_text(json.dumps(data))

    sender("sender-ready", [f"TELEGRAM_BOT_TOKEN={TOKEN}", f"TELEGRAM_HOME_CHANNEL={HOME_CHANNEL}"])
    sender("sender-new")                                              # created, never set up
    sender("sender-no-start", [f"TELEGRAM_BOT_TOKEN={TOKEN}"])        # the bot has no chat yet
    sender("sender-named", [f"TELEGRAM_BOT_TOKEN={TOKEN}"],
           {"channel_directory.json": {"platforms": {"telegram": [{"id": HOME_CHANNEL, "name": "owner",
                                                                   "type": "dm"}]}}})
    cases = [
        ("a bot token and a home channel; push_to \"telegram\"", "sender-ready", "telegram"),
        ("a profile with no .env at all", "sender-new", "telegram"),
        ("a bot token, no home channel; push_to \"telegram\"", "sender-no-start", "telegram"),
        ("a bot token; push_to names a chat its channel directory has", "sender-named", "telegram:owner"),
        ("a bot token; push_to names a chat its channel directory lacks", "sender-named", "telegram:someone"),
        ("a profile that does not exist", "sender-gone", "telegram"),
        ("a target on another platform", "sender-ready", "discord:ops"),
    ]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("KEVIN_PUSH_", "HERMES_", "TELEGRAM_"))}
    env["HERMES_HOME"] = str(root)
    for why, name, to in cases:
        print(f"# {why}")
        print(doctor.text([doctor.push_sender_row({"push_profile": name, "push_to": to}, env)]))
