"""The synthetic desktop ActivityWatch example in docs/desktop-aw.md: python3 -I scripts/desktop_aw_example.py

A made-up desktop: a fake fetch serves two buckets the way aw-server's REST API does (a ``currentwindow``
bucket whose events carry a planted window title, and an ``afkstatus`` bucket), so nothing touches the
network. It runs the real reader (aw_desktop.read_events), the doctor's row in each state, and the flow
ledger and flow metrics words with the desktop as the only source. Writes nothing outside a temporary dir,
sends nothing, reads no real state.
"""
import json
import os
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import aw_desktop, doctor, flow_ledger, flow_metrics  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

for k in [k for k in os.environ if k.startswith("LIMITLESS_")]:
    del os.environ[k]
os.environ["TZ"] = "UTC"
if hasattr(time, "tzset"):
    time.tzset()

DAY = date(2030, 1, 14)
NOW = 1894708800.0                       # 2030-01-15T12:00:00Z, the fixture clock
URL = "http://desktop.invalid:5600"      # a made-up address; the fake fetch answers, nothing is dialled
PLANTED = "PLANTED-WINDOW-TITLE"


def at(hour: float) -> float:
    return datetime(DAY.year, DAY.month, DAY.day, tzinfo=timezone.utc).timestamp() + hour * 3600


def ev(start_h, end_h, **data):
    return {"timestamp": datetime.fromtimestamp(at(start_h), timezone.utc).isoformat(),
            "duration": (end_h - start_h) * 3600, "data": data}


BUCKETS = {
    "aw-watcher-window_desk": {"type": "currentwindow", "hostname": "desk", "events": [
        ev(9, 10.5, app="editor", title=PLANTED), ev(10.5, 10.6, app="scroller", title=PLANTED),
        ev(10.6, 12, app="editor", title=PLANTED), ev(12, 14, app="editor", title=PLANTED),
        ev(14, 15, app="terminal", title=PLANTED)]},
    "aw-watcher-afk_desk": {"type": "afkstatus", "hostname": "desk", "events": [
        ev(9, 12, status="not-afk"), ev(12, 13, status="afk"), ev(13, 15, status="not-afk")]},
}


def fetch(url, timeout):
    path = urlsplit(url).path
    if path == "/api/0/buckets/":
        return json.dumps({k: {kk: v for kk, v in b.items() if kk != "events"} for k, b in BUCKETS.items()}).encode()
    bid = path[len("/api/0/buckets/"):-len("/events")]
    return json.dumps(BUCKETS[bid]["events"][::-1]).encode()


def down(url, timeout):
    raise OSError("no answer")


def hours(s, e):
    return f"{(s - at(0)) / 3600:g}-{(e - at(0)) / 3600:g}h"


got = aw_desktop.read_events(URL, at(0), at(24), fetch=fetch)
print("$ aw_desktop.read_events(url, day_start, day_end, fetch=<synthetic server>)")
print(f"state: {got['state']}")
for s, e, app in got["events"]:
    print(f"  {hours(s, e)} {app}")
print(f"planted title anywhere in the result: {PLANTED in json.dumps(got)}")

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    st.mkdir()
    cfg_path = root / "config.json"
    cfg = {"state": str(st), "desktop_aw_url": URL, "flow_work_apps": ["editor", "terminal"],
           "feed_apps": ["scroller"]}
    cfg_path.write_text(json.dumps(cfg))
    env = {"LIMITLESS_CONFIG": str(cfg_path), "HOME": str(root)}
    reader = StateReader(st)
    print("$ flow words with the desktop as the only source (no phone DB set)")
    with mock.patch.object(aw_desktop, "urllib_fetch", fetch):
        led = flow_ledger.read_for(reader, DAY, NOW, env, root, timezone.utc)
        met = flow_metrics.read_for(reader, at(0), at(24), env, root, timezone.utc)
    print(f"flow ledger: {flow_ledger.label(led)}")
    print(f"flow metrics: {flow_metrics.label(met['pool'], met['why'] or flow_metrics.NO_DATA, met['thresholds'])}")
    aw_desktop._HOLD.clear()
    with mock.patch.object(aw_desktop, "urllib_fetch", down):
        met = flow_metrics.read_for(reader, at(0), at(24), env, root, timezone.utc)
    print(f"flow metrics, desktop asleep: {flow_metrics.label(met['pool'], met['why'], met['thresholds'])}")
    aw_desktop._HOLD.clear()

    print("$ limitless-doctor (the desktop AW row only)")
    rows = [doctor.desktop_aw_row({"state": str(st)}, NOW),
            doctor.desktop_aw_row(cfg, at(16), fetch=fetch),
            doctor.desktop_aw_row(cfg, NOW + 3 * 86400, fetch=fetch),
            doctor.desktop_aw_row(cfg, NOW, fetch=down)]
    print(doctor.text([dict(r, reason=doctor.words(r["reason"])) for r in rows]))
