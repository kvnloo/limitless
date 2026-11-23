"""The synthetic phase example in docs/phase.md: python3 -I scripts/phase_example.py

A made-up state dir: Sleep mode on in the evening and off at the wake event, a live Sleep-mode poll, then a
wind-down event; a posture file written by a made-up circadian daemon. Reads no real state, writes nothing
outside a temporary dir, sends nothing. It runs the real limitless_phase tool body and the state card at a few
fixed synthetic clocks, each given as a span after the synthetic wake event.
"""
import json
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import card, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

UTC = timezone.utc
WAKE = datetime(2033, 3, 9, 6, 40, tzinfo=UTC).timestamp()
H, M = 3600.0, 60.0
KEYS = ("value", "modality", "age_h", "evidence_tier", "label", "why", "reason", "posture_ignored")


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def show(title, st, env, root, now):
    print(f"# {title}")
    res = tools.phase(StateReader(st), now, env=env, home=root)
    res = dict(res, label=res["label"]["label"])
    print(json.dumps({k: res[k] for k in KEYS if k in res}))


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    st.mkdir()
    (st / "sleepmode.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (
        {"at": iso(WAKE - 8 * H), "on": True}, {"at": iso(WAKE), "on": False})))
    env = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
    env.update(HOME=str(root), LIMITLESS_STATE=str(st), LIMITLESS_CONFIG=str(root / "config.json"))

    show("twenty minutes after the wake event", st, env, root, WAKE + 20 * M)
    print("# the state card at the same moment")
    print(card.build(StateReader(st), WAKE + 20 * M, date(2033, 3, 9), env=env)["text"])
    print()
    show("three hours after the wake event", st, env, root, WAKE + 3 * H)
    print("# the state card has no light line now:",
          "Light:" not in card.build(StateReader(st), WAKE + 3 * H, date(2033, 3, 9), env=env)["text"])
    print()
    (st / "events.jsonl").write_text(json.dumps({"event": "wind_down", "at": iso(WAKE + 14 * H)}) + "\n")
    show("after the wind-down event", st, env, root, WAKE + 14.5 * H)
    print()
    posture = root / "posture.json"
    posture.write_text(json.dumps({"phase": "day", "at": iso(WAKE + 30 * M), "model": "synthetic"}))
    env["LIMITLESS_POSTURE"] = str(posture)
    show("a posture file fresher than the wake event", st, env, root, WAKE + 40 * M)
    posture.write_text(json.dumps({"phase": "subjective_dusk", "at": iso(WAKE + 30 * M)}))
    show("a posture file with a phase name it does not know", st, env, root, WAKE + 40 * M)
    print()
    (st / "sleepmode.jsonl").write_text("")
    del env["LIMITLESS_POSTURE"]
    show("no wake event", st, env, root, WAKE + 40 * M)
