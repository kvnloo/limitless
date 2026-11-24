"""A synthetic Hermes profile that push_sender.readiness calls ready: a placeholder bot token and a chat.

    ready_profile(home)   # home: a profile dir (or the Hermes home itself for ``default``); returns it

Writes ``.env`` with a made-up ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_HOME_CHANNEL`` (a bare ``telegram`` target
uses the home channel) and a ``channel_directory.json`` entry for the name in push_sender.TARGET_DEFAULT (a named
target is looked up there), so the profile is ready for either target. Placeholders only, never a real token or
chat. Shared by the sender reply tests, the sender ingest job tests and scripts/sender_ingest_example.py.
"""
import json
from pathlib import Path

TOKEN = "placeholder-token-not-real"


def ready_profile(home):
    from limitless import push_sender
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    (home / ".env").write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_HOME_CHANNEL=placeholder-chat\n")
    name = push_sender.TARGET_DEFAULT.partition(":")[2]
    (home / "channel_directory.json").write_text(json.dumps(
        {"platforms": {"telegram": [{"id": "placeholder-chat", "name": name, "type": "dm"}]}}))
    return home
