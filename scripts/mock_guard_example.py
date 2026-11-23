"""The synthetic example in docs/mock-guard.md: python3 -I scripts/mock_guard_example.py

Builds a made-up NOOP DB (tests/noop_fixture.py) holding real nights, nights from a demo strap id and nights the
demo dataset marks only by its device name; runs limitless-noop-export as a dry run, then against a DB of only
demo rows with --write; serves a made-up Open Wearables seed user through an injected http callable; asks
limitless_status about an inputs.json that names a demo device; prints the doctor rows. Reads no real state,
writes nothing outside the temp dir, sends nothing. UTC stands in for the local zone.
"""
import io
import json
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "tests"))
from limitless import doctor, noop_export, open_wearables as ow, tools  # noqa: E402
from limitless.state_reader import StateReader, config  # noqa: E402
from noop_fixture import RING, hr_before, make_db, stages  # noqa: E402

UTC = timezone.utc
H = 3600
TODAY = date(2030, 1, 8)
NOW = datetime.combine(TODAY, time(9), UTC).timestamp()
USER = "00000000-0000-4000-8000-0000000000aa"
KEY = "ow-SYNTHETIC-key-7f3a9c"   # a made-up key, never printed


def at(d, hh):
    return int(datetime.combine(d, time(hh), UTC).timestamp())


def nights(device, first, n):
    sessions, hr = [], []
    for i in range(n):
        on = at(first + timedelta(days=i), 23)
        sessions.append((device, on, on + 8 * H, 0.9, stages(on, 7 * H, H)))
        hr += hr_before(device, on, 60)
    return sessions, hr


def paired(i, kind):
    return {"id": i, "brand": "Band", "model": "Band", "nickname": None, "peripheralId": None, "sourceKind": kind,
            "capabilities": "hr,sleep", "status": "paired", "addedAt": 0, "lastSeenAt": 0}


def run(argv, env, root):
    out = io.StringIO()
    code = noop_export.main(argv, env=env, home=root, tz=UTC, out=out, err=out)
    print(out.getvalue().rstrip())
    print(f"  (exit {code})")
    print()


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    st.mkdir()
    cfg_path = root / "config.json"
    cfg = {"noop_db": "noop-copy.db", "sleep_file": "sleep.jsonl", "presleep_hr_file": "presleep-hr.jsonl",
           "open_wearables_export": "write", "open_wearables_url": "http://ow.example.invalid:8000",
           "open_wearables_user": USER, "mock_device_patterns": ["sim-*"]}
    cfg_path.write_text(json.dumps(cfg))
    env = {"LIMITLESS_CONFIG": str(cfg_path), "LIMITLESS_STATE": str(st), ow.KEY_ENV: KEY}
    devices = [paired(RING, "oura"), paired("demo-band-a", "liveBLE"), paired("sim-band-c", "liveBLE")]

    groups = [nights(RING, date(2030, 1, 1), 2), nights("demo-band-a", date(2030, 1, 3), 2),
              nights("my-whoop", date(2030, 1, 5), 1), nights("sim-band-c", date(2030, 1, 6), 1)]
    make_db(st / "noop-copy.db", sessions=[s for g in groups for s in g[0]], hr=[h for g in groups for h in g[1]],
            devices=devices, names=[("my-whoop", "Band (demo)")])
    print("$ limitless-noop-export   (two real nights; two from a demo- id, one the demo device name marks, one "
          "matching mock_device_patterns)")
    run([], env, root)

    (st / "noop-copy.db").unlink()
    make_db(st / "noop-copy.db", sessions=groups[1][0], hr=groups[1][1], devices=devices)
    print("$ limitless-noop-export --write   (only demo rows)")
    run(["--write"], env, root)
    print(f"sleep file written: {(st / 'sleep.jsonl').exists()}")
    print()

    def seed_server(url, headers, timeout):
        if url.split("?")[0].endswith("/events/sleep"):
            s = {"start_time": "2030-01-01T23:00:00Z", "end_time": "2030-01-02T06:00:00Z", "is_nap": False,
                 "sleep_duration_seconds": 24000, "source": {"provider": "polar", "device_type": "watch"}}
            return 200, json.dumps({"data": [s], "pagination": {"has_more": False}}).encode()
        return 200, json.dumps({"id": USER, "first_name": "[SEED:7|active] Synthetic"}).encode()

    print("$ limitless-ow-export --write   (the user is an Open Wearables seed user)")
    out = io.StringIO()
    code = ow.main(["--write"], env=env, home=root, tz=UTC, out=out, err=out, http=seed_server, today=TODAY,
                   now=NOW - H)
    print(out.getvalue().rstrip())
    print(f"  (exit {code})")
    print()

    iso = datetime.fromtimestamp(NOW - 1800, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    (st / "inputs.json").write_text(json.dumps({"at": iso, "ageHours": {"wearable": 1.0, "demo-band-a": 0.1,
                                                                        "sim-band-c": 0.1}}))
    got = tools.status(StateReader(st), NOW, config(env, root))["value"]
    print("limitless_status inputs:")
    for name, v in got["inputs"].items():
        print(f"  {name}: {v['state']}")
    print(f"  unknown: {', '.join(got['unknown'])}")
    print()

    print("$ limitless-doctor | grep -E 'input|export'")
    for r in doctor.report(dict(config(env, root), state=str(st)), NOW):
        if r["kind"] == "input" or r["name"] in (doctor.OW_ROW,):
            print(f"{r['name']}: {r['status']}: {r['reason']}")
