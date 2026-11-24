"""The synthetic push-reach example in docs/push-reach.md: python3 -I scripts/push_reach_example.py

A made-up state dir (a copy of the synthetic fixture state, tests/fixtures/state), a made-up Hermes home and a
made-up kevin-push log, all in a temporary dir, at the fixture clock in UTC. Four cases: the sender profile is
missing, the sender is set but the last pushes failed to send (no profile has a bot, then one made-up profile
``helper`` with a made-up token and chat key, so the card names the reply), and the sender is set with the last
push delivered. For each it prints the real pre_llm_call card (card.make_pre_llm_call, through tier_audit.gate),
limitless_status's ``delivery`` (tools.status_with_delivery) and the context packet's ``delivery`` row. Reads no
real state, never runs hermes, writes nothing outside the temporary dir, sends nothing.
"""
import json
import os
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import card, context_packet, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 1894708800.0   # 2030-01-15T12:00:00Z, the fixture clock
TODAY = date(2030, 1, 15)
DAY = TODAY - timedelta(days=3)
FIX = REPO / "tests" / "fixtures" / "state"
PROFILE = "sender-a"
RC1 = "log (telegram rc=1)"

os.environ["TZ"] = "UTC"
if hasattr(time, "tzset"):
    time.tzset()


def log_row(hour, how="telegram"):
    at = int(datetime(DAY.year, DAY.month, DAY.day, hour, 0, tzinfo=timezone.utc).timestamp())
    return {"at": at, "tag": "x", "cls": "decision", "title": "Pick one", "how": how,
            "body": "Keep the loop?\nReply: Yes / No"}


CASES = (
    ("the sender profile is not in the Hermes home; the last push was delivered", False,
     [log_row(10, RC1), log_row(11, RC1), log_row(12)], False),
    ("the sender profile is there; the last two pushes logged telegram rc=1", True,
     [log_row(10), log_row(11, RC1), log_row(12, RC1)], False),
    ("the same, and profile helper has a Telegram bot token and chat", True,
     [log_row(10), log_row(11, RC1), log_row(12, RC1)], True),
    ("the sender profile is there; the last push was delivered", True,
     [log_row(10, RC1), log_row(11, RC1), log_row(12)], False),
)

with tempfile.TemporaryDirectory() as tmp:
    for n, (what, sender, rows, helper) in enumerate(CASES):
        root = Path(tmp) / f"case{n}"
        st = root / "state"
        st.mkdir(parents=True)
        for f in FIX.iterdir():
            (st / f.name).write_bytes(f.read_bytes())
        hermes = root / "hermes"
        (hermes / "profiles" / "other").mkdir(parents=True)
        if sender:
            (hermes / "profiles" / PROFILE).mkdir()
        if helper:
            (hermes / "profiles" / "helper").mkdir()
            (hermes / "profiles" / "helper" / ".env").write_text(
                "TELEGRAM_BOT_TOKEN=made-up-token\nTELEGRAM_HOME_CHANNEL=made-up-chat\n")
        (st / "push-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        cfg = {"push_profile": PROFILE, "push_to": "telegram", "push_log": "push-log.jsonl"}
        (root / "config.json").write_text(json.dumps(cfg))
        env = {"HOME": str(root), "HERMES_HOME": str(hermes), "LIMITLESS_STATE": str(st),
               "LIMITLESS_CONFIG": str(root / "config.json")}
        print(f"# {what}")
        print("$ pre_llm_call card")
        print(card.make_pre_llm_call(env=env, clock=lambda: NOW, today=lambda: TODAY)()["context"])
        print("$ limitless_status: delivery")
        print(json.dumps(tools.status_with_delivery(StateReader(st), NOW, cfg, env, TODAY)["delivery"],
                         ensure_ascii=False))
        print("$ limitless-context-packet: delivery row")
        p = context_packet.packet(st, NOW, TODAY, env)
        print(next(ln for ln in context_packet.text(p).splitlines() if ln.startswith("delivery:")))
        if n + 1 < len(CASES):
            print()
