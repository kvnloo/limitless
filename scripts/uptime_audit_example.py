"""The synthetic uptime-audit example in docs/uptime-audit.md: python3 -I scripts/uptime_audit_example.py

Four weeks of synthetic sync rows in the shape the sync appends to runs.jsonl ({at, job, ok} and, on newer rows,
inputs: "stale a,b"), with a synthetic inputs.json, in a temporary state dir, at a fixed clock in UTC. Reads no
real state, writes nothing outside that dir, sends nothing. It runs the limitless_uptime tool (without and with
the raw opt-in), then with config outage_ignore and uptime_days, then over older rows only, then with loop gaps
(also while too few runs name their inputs).
"""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

UTC = timezone.utc
NOW = datetime(2033, 5, 18, 20, 0, tzinfo=UTC).timestamp()
DAY, HOUR = 86400, 3600
NAMES = ["phoneApps", "phoneUnlocks", "wearable", "desktopAW"]


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync(days_ago, hour, stale=None):
    r = {"at": iso(NOW - days_ago * DAY - (20 - hour) * HOUR), "job": "sync", "ok": True}
    if stale is not None:
        r["inputs"] = "stale " + ",".join(stale)
    return r


ROWS = [sync(n, 9) for n in range(27, 21, -1)]                  # older rows: no inputs key, unknown
ROWS += [sync(n, 9, ["wearable", "desktopAW"]) for n in range(21, 14, -1)]
ROWS += [sync(n, 9, ["desktopAW"]) for n in range(14, 9, -1)]
ROWS += [sync(9, 6, ["wearable"]), sync(9, 12, [])]              # stale early, fresh later: a fresh day
# days eight and seven ago: no run at all (unknown)
ROWS += [sync(n, 9, ["desktopAW"] if n % 2 else []) for n in range(6, -1, -1)]

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    st.mkdir()
    (st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in ROWS) + "{a cut line\n")
    (st / "inputs.json").write_text(json.dumps({"at": iso(NOW - HOUR), "ageHours": {n: 1.0 for n in NAMES}}))
    cfg = root / "config.json"
    env = {"LIMITLESS_CONFIG": str(cfg)}
    reader = StateReader(st)
    keep = ("value", "modality", "age_h", "evidence_tier", "reason")

    cfg.write_text(json.dumps({}))
    print("# limitless_uptime, no raw opt-in (default window: four weeks, target nineteen days in twenty)")
    res = tools.uptime(reader, NOW, env=env, home=root, tz=UTC)
    print(json.dumps({k: res[k] for k in keep if k in res}))
    print(json.dumps(res["label"]))

    print("\n# the same with the raw opt-in: T0 counts per input, then per day (null = unknown day)")
    v = tools.uptime(reader, NOW, raw=True, env=env, home=root, tz=UTC)["value"]
    for name, c in v["inputs"].items():
        print(name, json.dumps(c))
    print(json.dumps({k: v[k] for k in ("window_days", "known_days", "all_fresh_days", "all_fresh_share", "target",
                                        "goal", "skipped")}))
    for d in v["days"][-12:]:
        print(json.dumps(d))

    print("\n# config outage_ignore: [\"desktopAW\"] (the same names the outage line leaves out)")
    cfg.write_text(json.dumps({"outage_ignore": ["desktopAW"]}))
    print(tools.uptime(reader, NOW, env=env, home=root, tz=UTC)["label"]["label"])

    print("\n# config uptime_days: 7, outage_ignore: [\"desktopAW\"]")
    cfg.write_text(json.dumps({"outage_ignore": ["desktopAW"], "uptime_days": 7}))
    print(tools.uptime(reader, NOW, env=env, home=root, tz=UTC)["label"]["label"])

    print("\n# only older rows (no inputs key): unknown, never fresh")
    old = st / "old"
    old.mkdir()
    (old / "runs.jsonl").write_text("".join(json.dumps(sync(n, 9)) + "\n" for n in range(28)))
    res = tools.uptime(StateReader(old), NOW, env=env, home=root, tz=UTC)
    print(json.dumps({k: res[k] for k in keep if k in res}))

    print("\n# a loop that stopped: hourly runs, none for eight hours three days ago and none in the last five hours")
    gaps = st / "gaps"
    gaps.mkdir()
    hourly = [NOW - 5 * HOUR - k * HOUR for k in range(27 * 24)]
    hourly = [t for t in hourly if not NOW - 3 * DAY - 8 * HOUR < t < NOW - 3 * DAY]
    (gaps / "runs.jsonl").write_text("".join(json.dumps({"at": iso(t), "job": "sync", "ok": True, "inputs": "stale"})
                                             + "\n" for t in sorted(hourly)))
    (gaps / "inputs.json").write_text(json.dumps({"at": iso(NOW - HOUR), "ageHours": {n: 1.0 for n in NAMES}}))
    cfg.write_text(json.dumps({}))
    print(tools.uptime(StateReader(gaps), NOW, env=env, home=root, tz=UTC)["label"]["label"])
    print("# the same with config loop_gap_limit_s: eight hours (neither stretch is over it)")
    cfg.write_text(json.dumps({"loop_gap_limit_s": 8 * HOUR}))
    print(tools.uptime(StateReader(gaps), NOW, env=env, home=root, tz=UTC)["label"]["label"])

    print("\n# a loop that stopped while too few runs name their inputs: hourly runs, none for two days ending two"
          " days ago,\n# only the newest three with an inputs key (the goal is unknown, the stop is not)")
    few = st / "few"
    few.mkdir()
    hourly = [NOW - HOUR / 2 - k * HOUR for k in range(5 * 24)]
    hourly = sorted(t for t in hourly if not NOW - 4 * DAY < t < NOW - 2 * DAY)
    rows = [{"at": iso(t), "job": "sync", "ok": True} for t in hourly]
    for r in rows[-3:]:
        r["inputs"] = "stale"
    (few / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    cfg.write_text(json.dumps({}))
    res = tools.uptime(StateReader(few), NOW, env=env, home=root, tz=UTC)
    print(json.dumps({k: res[k] for k in keep if k in res}))

    print("\n# runs.jsonl is unchanged:", (st / "runs.jsonl").read_text().count("\n"), "lines")
