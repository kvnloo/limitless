"""The synthetic delivery-audit example in docs/delivery-audit.md: python3 -I scripts/delivery_audit_example.py

A week of synthetic push-log rows in the shape bin/kevin-push writes ({at, tag, cls, title, body, how}) and three
synthetic wake events, in a temporary state dir, at a fixed clock in UTC. Reads no real state, writes nothing
outside that dir, sends nothing. It runs the limitless_delivery tool (without and with the raw opt-in) and the
week review line.
"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import jobs_runner, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

UTC = timezone.utc
NOW = datetime(2033, 5, 18, 20, 0, tzinfo=UTC).timestamp()
DAY = 86400
BRIEF = "Wake-up brief"
WHY = "Why now: you woke up"


def at(days_ago, hour):
    return int(NOW - days_ago * DAY - (20 - hour) * 3600)


def push(days_ago, hour, title, body, how="telegram", tag="x", cls="decision"):
    return {"at": at(days_ago, hour), "tag": tag, "cls": cls, "title": title, "body": body, "how": how}


ROWS = [
    push(4, 7, BRIEF, f"Good morning.\nReply: Ok\n{WHY}", tag="limitless", cls="report"),
    push(4, 9, "Pick one", "Keep the loop?\nReply: Yes / No\nWhy now: you are awake and this fits any moment"),
    push(4, 10, "Sync report", "all synced", how="log", cls="report"),
    push(3, 7, BRIEF, "Good morning.", how="held (sleep mode)", tag="limitless", cls="report"),
    push(3, 8, "Asks waiting on you", "A1: one", how="folded (brief line)", tag="asks"),
    push(1, 7, BRIEF, f"Good morning.\n{WHY}", tag="limitless", cls="report"),
    push(1, 9, "Heads up", "The build finished.\nWhy now: you are awake and this fits any moment"),
    push(1, 11, "Pick one", "Keep the loop?\nReply: Yes / No", how="log (duplicate)"),
]
WAKES = [at(4, 6), at(3, 6), at(1, 6)]

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    st.mkdir()
    (st / "push-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in ROWS) + "{a cut line\n")
    (st / "events.jsonl").write_text("".join(json.dumps({"event": "wake", "at": w}) + "\n" for w in WAKES))
    cfg = root / "config.json"
    env = {"LIMITLESS_CONFIG": str(cfg)}
    reader = StateReader(st)
    keep = ("value", "modality", "age_h", "evidence_tier", "reason")

    print("# no push log set")
    cfg.write_text(json.dumps({}))
    res = tools.delivery(reader, NOW, env=env, home=root, tz=UTC)
    print(json.dumps({k: res[k] for k in keep if k in res}))
    print(json.dumps(res["label"]))

    cfg.write_text(json.dumps({"push_log": "push-log.jsonl"}))
    print("\n# push_log set (relative: in the state dir); limitless_delivery, no raw opt-in")
    res = tools.delivery(reader, NOW, env=env, home=root, tz=UTC)
    print(json.dumps({k: res[k] for k in keep if k in res}))

    print("\n# the same with the raw opt-in: T0 counts per day (None = no row that day: unknown)")
    v = tools.delivery(reader, NOW, raw=True, env=env, home=root, tz=UTC)["value"]
    for d in v["days"]:
        print(json.dumps(d))
    print(json.dumps({k: v[k] for k in ("delivered", "known_days", "cap", "over_cap_days", "no_action",
                                        "action_unknown", "skipped")}))
    print(json.dumps(v["wake"]))

    print("\n# week review line")
    print(jobs_runner.week_delivery(st, env, root, datetime.fromtimestamp(NOW, UTC).date(), UTC, NOW))

    print("\n# the log is unchanged:", (st / "push-log.jsonl").read_text().count("\n"), "lines")
