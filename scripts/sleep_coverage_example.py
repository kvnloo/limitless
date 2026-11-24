"""The synthetic sleep-coverage example in docs/sleep-coverage.md: python3 -I scripts/sleep_coverage_example.py

Four weeks of synthetic wearable sleep rows in the shape StateReader.sleep_rows reads ({night, asleep_s, source}),
some of them marked as demo rows the way the source apps mark them, beside synthetic phone unlock rows (the
phone estimate), in a temporary state dir, at a fixed clock in UTC. Reads no real state, writes nothing outside
that dir, sends nothing. It runs the limitless_sleep_coverage tool without and with the raw opt-in, then with
config sleep_coverage_days, then with no sleep file.
"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

UTC = timezone.utc
NOW = datetime(2033, 5, 18, 9, 0, tzinfo=UTC).timestamp()
TODAY = datetime.fromtimestamp(NOW, UTC).date()
HOUR = 3600


def night(ago):
    return (TODAY - timedelta(days=ago)).isoformat()


def wear(ago, **mark):
    return dict({"night": night(ago), "asleep_s": 7 * HOUR, "source": "synthetic-band"}, **mark)


def unlocks(ago):
    """Two synthetic unlocks around a quiet phone span from 23:00 on the evening ``ago`` nights back."""
    d = TODAY - timedelta(days=ago)
    s = datetime(d.year, d.month, d.day, 23, tzinfo=UTC).timestamp()
    return [{"ts": int(s * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"},
            {"ts": int((s + 8 * HOUR) * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"}]


SLEEP = [wear(n) for n in range(1, 8)]                              # the last week: the wearable every night
SLEEP += [wear(n) for n in (9, 12, 15)]                             # then only now and then
SLEEP += [wear(n, deviceId="demo-strap") for n in (8, 10, 11)]      # a demo seeder's strap id: never counts
SLEEP += [wear(n, source="synthetic-band-demo") for n in (13, 14)]  # a demo source name: never counts
PHONE = [r for n in range(1, 26) for r in unlocks(n)]               # nights twenty-six to twenty-eight: nothing

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    st.mkdir()
    (st / "sleep.jsonl").write_text("".join(json.dumps(r) + "\n" for r in SLEEP))
    (st / "screen-events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in PHONE))
    cfg = root / "config.json"
    env = {"LIMITLESS_CONFIG": str(cfg)}
    reader = StateReader(st)
    keep = ("value", "modality", "age_h", "evidence_tier", "reason")

    cfg.write_text(json.dumps({"sleep_file": "sleep.jsonl"}))
    print("# limitless_sleep_coverage, no raw opt-in (default window: four weeks, target four nights in five)")
    res = tools.sleep_coverage(reader, NOW, env=env, home=root, tz=UTC)
    print(json.dumps({k: res[k] for k in keep if k in res}))
    print(json.dumps(res["label"]))

    print("\n# the same with the raw opt-in: T0 counts")
    v = tools.sleep_coverage(reader, NOW, raw=True, env=env, home=root, tz=UTC)["value"]
    print(json.dumps({k: v[k] for k in tools.SLEEP_COVERAGE_RAW_KEYS}))

    print("\n# config sleep_coverage_days: 7")
    cfg.write_text(json.dumps({"sleep_file": "sleep.jsonl", "sleep_coverage_days": 7}))
    print(tools.sleep_coverage(reader, NOW, env=env, home=root, tz=UTC)["label"]["label"])

    print("\n# config sleep_coverage_days: 14, sleep_coverage_target: 0.5")
    cfg.write_text(json.dumps({"sleep_file": "sleep.jsonl", "sleep_coverage_days": 14, "sleep_coverage_target": 0.5}))
    print(tools.sleep_coverage(reader, NOW, env=env, home=root, tz=UTC)["label"]["label"])

    print("\n# sleep_file set, but the file is not there: unknown, never zero, and the reason names no path")
    cfg.write_text(json.dumps({"sleep_file": "gone.jsonl"}))
    res = tools.sleep_coverage(reader, NOW, env=env, home=root, tz=UTC)
    print(json.dumps({k: res[k] for k in keep if k in res}))

    print("\n# no sleep_file set")
    cfg.write_text(json.dumps({}))
    print(tools.sleep_coverage(reader, NOW, env=env, home=root, tz=UTC)["reason"])

    print("\n# sleep.jsonl is unchanged:", (st / "sleep.jsonl").read_text().count("\n"), "lines")
