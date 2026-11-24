"""The synthetic sender candidates example in docs/doctor.md: python3 -I scripts/sender_candidates_example.py

A made-up Hermes home in a temp dir with made-up profiles (alpha, beta, ...; a made-up placeholder token, a
made-up home channel) and limitless-doctor's real "sender candidates" row (doctor.sender_candidates_row, which asks
push_sender.candidates), then the real "push recovery" row while pushes fail (made-up log rows). Files only: it
never runs hermes, never sends and reads no real state. The token value is never printed: only whether it is there.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import doctor, push_sender  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

TOKEN = "made-up-token-never-printed"
NOW = 1894708800.0   # a fixed made-up clock
H = 3600.0
READY_ENV = f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_HOME_CHANNEL=made-up-chat\n"

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    root = tmp / "hermes"
    (root / "profiles").mkdir(parents=True)

    def profile(name, env_text=None, config=None, home=root):
        d = home / "profiles" / name
        d.mkdir(parents=True)
        if env_text is not None:
            (d / ".env").write_text(env_text)
        if config is not None:
            (d / "config.yaml").write_text(config)

    base = {k: v for k, v in os.environ.items() if not k.startswith(("KEVIN_PUSH_", "HERMES_", "TELEGRAM_"))}
    env = dict(base, HERMES_HOME=str(root))
    cfg = {"push_profile": "gone", "push_to": "telegram"}

    def show(why, e=env):
        print(f"# {why}")
        print(doctor.text([doctor.sender_candidates_row(cfg, e)]))

    profile("alpha", READY_ENV)
    profile("beta", READY_ENV)
    profile("gamma", "TELEGRAM_HOME_CHANNEL=made-up-chat\n")      # a chat, but no Telegram bot token
    show("alpha and beta have a bot token and a home channel; gamma has no token; default has none")
    profile("delta", config="secrets:\n  telegram:\n    source: made-up-vault\n")
    show("delta keeps its token in a secret source")
    profile("epsilon", READY_ENV)
    (root / "profiles" / push_sender.DELETED_DIR).mkdir()
    (root / "profiles" / push_sender.DELETED_DIR / "epsilon").write_bytes(b"deleted\n")
    show("epsilon is ready but deleted (profiles/.deleted/epsilon): skipped")
    lone = tmp / "lone"
    (lone / "profiles").mkdir(parents=True)
    profile("gamma", "TELEGRAM_HOME_CHANNEL=made-up-chat\n", home=lone)
    lone_env = dict(base, HERMES_HOME=str(lone))
    show("a Hermes home where no profile has a bot token", lone_env)
    show("HERMES_HOME names a dir that does not exist", dict(base, HERMES_HOME=str(tmp / "nowhere")))

    st = tmp / "state"
    st.mkdir()
    rows = [{"at": int(NOW - at * H), "tag": "limitless", "cls": "report", "title": "Wake-up brief",
             "body": "Made-up body.", "how": how}
            for at, how in ((5, "telegram"), (3, push_sender.NO_SENDER_HOW), (2, push_sender.NO_SENDER_HOW))]
    (st / "push-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    rcfg = dict(cfg, push_log="push-log.jsonl")
    print("# two pushes failed in a row; no reply yet")
    print(doctor.text([doctor.push_recovery_row(StateReader(st), rcfg, NOW, env=env)]))
    print("# the same, on the Hermes home where no profile has a bot token")
    print(doctor.text([doctor.push_recovery_row(StateReader(st), rcfg, NOW, env=lone_env)]))
