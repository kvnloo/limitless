"""The synthetic breathing-link example in docs/breathing-link.md: python3 -I scripts/breathing_link_example.py

A temporary state dir with a synthetic wind-down event and a fixed clock. It runs limitless-jobs' one pass
(jobs_runner.run_once) with a stand-in push that only prints what would be sent, first with no breathing link
(the default), then with the synthetic link example://breathe and a fresh wearable input, then with the
wearable input stale. It reads limitless_breathing through the plugin handler, without and with the raw
opt-in. Reads no real state, writes nothing outside the temporary dir, sends nothing.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import jobs, jobs_runner, plugin  # noqa: E402

NOW = 1894708800.0                # a fixed synthetic clock
H = 3600.0
LINK = "example://breathe"        # synthetic: stands for the person's own breathing app


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def push(title, body, once=None, why=None):
    print(f"push: {title}")
    for ln in body.splitlines():
        print(f"  {ln}")
    return "telegram"


def miq(st, env, root, step):
    sent = st / jobs_runner.SENT_LOG
    if sent.exists():
        sent.unlink()                 # a fresh night for each step of the example
    print(f"$ {step}: limitless-jobs --send (MIQ only shown)")
    with mock.patch.dict(os.environ, env, clear=True):
        rows = jobs_runner.run_once(st, NOW, push=lambda t, b, once=None, why=None:
                                    push(t, b) if t == jobs.MIQ.send_title else "telegram",
                                    dry_run=False, env=env, home=root, tz=timezone.utc)
    print("  MIQ verdict: " + ", ".join(r["action"] for r in rows if r["job"] == jobs.MIQ.send_title))


def tool(env, raw=False):
    env = dict(env, **({"LIMITLESS_RAW_IN_PROMPT": "1"} if raw else {}))
    with mock.patch.dict(os.environ, env, clear=True), mock.patch("time.time", return_value=NOW):
        out = json.loads(plugin._handler(plugin.TOOLS["limitless_breathing"][1], "limitless_breathing")({}))
    print("$ limitless_breathing" + (" (LIMITLESS_RAW_IN_PROMPT=1)" if raw else ""))
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))


def wearable(st, age_h):
    (st / "inputs.json").write_text(json.dumps({"at": iso(NOW - 0.5 * H), "ageHours": {"wearable": age_h}}))


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    st.mkdir()
    cfg = root / "config.json"
    rows = [{"at": NOW - 14 * H, "on": True}, {"at": NOW - 6 * H, "on": False}]
    (st / "sleepmode.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
    (st / "unlocks.jsonl").write_text(json.dumps({"at": NOW - 120}) + "\n")
    (st / "events.jsonl").write_text(json.dumps({"event": "wind_down", "at": NOW - 60}) + "\n")
    glide = root / "attention.json"   # synthetic Glide state: the wind-down began, Glide sent no nudge tonight
    glide.write_text(json.dumps({"block": None, "queue": [], "resume": {"saved": NOW - 120}, "nudged": ""}))
    env = {"LIMITLESS_CONFIG": str(cfg), "LIMITLESS_STATE": str(st), "LIMITLESS_GLIDE_ATTENTION": str(glide)}

    cfg.write_text(json.dumps({}))
    miq(st, env, root, "no breathing link (the default)")
    tool(env)

    cfg.write_text(json.dumps({"wind_down_breathing_link": LINK}))
    wearable(st, 0.4)
    miq(st, env, root, "link set, wearable input fresh")
    tool(env)
    tool(env, raw=True)

    wearable(st, 30.0)
    miq(st, env, root, "link set, wearable input stale")
    tool(env)
