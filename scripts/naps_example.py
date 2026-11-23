"""The synthetic naps example in docs/naps.md: python3 -I scripts/naps_example.py

Synthetic Sleep-mode rows in a temporary state dir; reads no real state, writes nothing else, sends nothing.
UTC stands in for the local zone.
"""
import json
import os
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from limitless import jobs, jobs_runner, naps, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

UTC = timezone.utc
TODAY = date(2030, 3, 12)
YESTERDAY = TODAY - timedelta(days=1)
NOW = datetime.combine(TODAY, time(7, 30), UTC).timestamp()


def row(d, hh, mm, on):
    return {"at": datetime.combine(d, time(hh, mm), UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "on": on}


NIGHTS = [row(YESTERDAY - timedelta(days=1), 23, 0, True), row(YESTERDAY, 7, 0, False),
          row(YESTERDAY, 23, 0, True), row(TODAY, 7, 0, False)]
CASES = {
    "no nap": [],
    "one nap after lunch": [row(YESTERDAY, 13, 0, True), row(YESTERDAY, 13, 30, False)],
    "one nap in the evening": [row(YESTERDAY, 20, 0, True), row(YESTERDAY, 20, 40, False)],
    "two naps": [row(YESTERDAY, 13, 0, True), row(YESTERDAY, 13, 30, False),
                 row(YESTERDAY, 16, 0, True), row(YESTERDAY, 16, 20, False)],
    "a long afternoon sleep (not a nap)": [row(YESTERDAY, 13, 0, True), row(YESTERDAY, 15, 30, False)],
    "Sleep mode still on (open, not a nap)": [row(YESTERDAY, 20, 0, True)],
}

print("naps.day, yesterday:")
for name, extra in CASES.items():
    evs = jobs.events_from_sleepmode(NIGHTS[:2] + extra + ([] if name.startswith("Sleep mode still") else NIGHTS[2:]))
    print(f"  {name}: {naps.day(evs, YESTERDAY, tz=UTC)['label']['label']}")
print(f"  no Sleep-mode change yesterday: {naps.day([], YESTERDAY, tz=UTC)['label']['label']}")

with tempfile.TemporaryDirectory() as tmp:
    st = Path(tmp) / "state"
    st.mkdir()
    rows = NIGHTS[:2] + CASES["one nap in the evening"] + NIGHTS[2:]
    (st / "sleepmode.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    env = {"LIMITLESS_CONFIG": str(Path(tmp) / "none.json")}
    print("\nlimitless_naps:")
    print(" ", json.dumps(tools.naps(StateReader(st), NOW, TODAY, env=env, tz=UTC)))
    print("limitless_naps under the raw opt-in:")
    print(" ", json.dumps(tools.naps(StateReader(st), NOW, TODAY, raw=True, env=env, tz=UTC)))
    print("\nwake brief line:")
    print(" ", jobs_runner.brief_naps(st, NOW, env, Path(tmp), UTC))
    print("week review line:")
    print(" ", jobs_runner.week_naps(st, env, Path(tmp), TODAY, UTC))
