"""The synthetic example in docs/noop-export.md: python3 -I scripts/noop_export_example.py

Builds a made-up NOOP DB (tests/noop_fixture.py: NOOP's public table and column names) in a temporary state dir,
runs limitless-noop-export as a dry run, with --write, and with --write again, then asks limitless_sleep and
limitless_presleep_hr. Reads no real state, writes nothing outside the temp dir, sends nothing. UTC stands in
for the local zone.
"""
import io
import json
import os
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "tests"))
from limitless import noop_export, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from noop_fixture import IMPORT, PHONE, RING, hr_before, make_db, stages  # noqa: E402

UTC = timezone.utc
H = 3600
TODAY = date(2030, 1, 28)
NOW = datetime.combine(TODAY, time(9), UTC).timestamp()


def at(d, hh, mm=0):
    return int(datetime.combine(d, time(hh, mm), UTC).timestamp())


sessions, hr = [], []
for i in range(16):                       # sixteen wearable nights, the last one ending this morning
    d = TODAY - timedelta(days=16 - i)
    on = at(d, 22 + i % 2, 15 * (i % 4))
    sessions.append((RING, on, on + 8 * H, None, stages(on, 7 * H + 600 * (i % 5), 1800)))
    if d != TODAY - timedelta(days=5):    # one night the ring recorded too little heart rate before sleep
        hr += hr_before(RING, on, 58 + i % 4)
    else:
        hr += hr_before(RING, on, 60, n=4)
nap = at(TODAY - timedelta(days=2), 15)
sessions.append((RING, nap, nap + 40 * 60, None, stages(nap, 30 * 60, 600)))           # a nap: not the night
phone = at(TODAY - timedelta(days=1), 23, 30)
sessions.append((PHONE, phone, phone + 7 * H, 0.9, None))                              # the phone: not a wearable
sessions.append((IMPORT, phone + 60, phone + 7 * H, 0.9, None))                         # a file import: skipped

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    st.mkdir()
    cfg = root / "config.json"
    cfg.write_text(json.dumps({"noop_db": "noop-copy.db", "sleep_file": "sleep.jsonl",
                               "presleep_hr_file": "presleep-hr.jsonl"}))
    env = {"LIMITLESS_CONFIG": str(cfg), "LIMITLESS_STATE": str(st)}
    make_db(st / "noop-copy.db", sessions=sessions, hr=hr)

    for args in ([], ["--write"], ["--write"]):
        out = io.StringIO()
        code = noop_export.main(args, env=env, home=root, tz=UTC, out=out, err=out)
        print(f"$ limitless-noop-export {' '.join(args)}".rstrip() + f"   (exit {code})")
        print(out.getvalue().rstrip())
        print()

    for name in ("sleep.jsonl", "presleep-hr.jsonl"):
        lines = (st / name).read_text().splitlines()
        print(f"last three rows of {name} ({len(lines)} rows, mode {oct((st / name).stat().st_mode & 0o777)}):")
        print("\n".join(lines[-3:]))
        print()

    reader = StateReader(st)
    s = tools.sleep(reader, NOW, TODAY, env=env, home=root, tz=UTC)
    p = tools.presleep_hr(reader, NOW, env=env, home=root, tz=UTC)
    print(f"limitless_sleep: modality {s['modality']}; {s['value']['label']}; {s['value']['regularity']}")
    print(f"limitless_presleep_hr: modality {p['modality']}; {(p['value'] or {}).get('label') or p.get('reason')}")
    print("files in the state dir:", ", ".join(sorted(x.name for x in st.iterdir())))
