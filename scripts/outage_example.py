"""The synthetic input-outage example in docs/outage.md: python3 -I scripts/outage_example.py

Synthetic inputs.json snapshots in a temporary state dir and a fixed clock; reads no real state, writes only
inside that temporary dir, sends nothing and restarts nothing. Each step is one wake brief: poll, build the
line, and mark it told as a delivered brief does.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from limitless import jobs_runner, outage  # noqa: E402

NOW = datetime(2030, 3, 12, 7, 30, tzinfo=timezone.utc).timestamp()
H = 3600.0
CFG = {"outage_hints": {"wearable": "Open the wearable's app once so it syncs again.",
                        "phone": "Open the app once to restart it."},
       "outage_ignore": ["scale"]}
STEPS = [   # (hours from the first brief, ageHours in inputs.json)
    ("day one: everything records", 0, {"wearable": 1.0, "phone": 0.5, "scale": 300.0}),
    ("day two: the wearable went quiet", 24, {"wearable": 26.0, "phone": 0.5, "scale": 324.0}),
    ("day three: still quiet, already said", 48, {"wearable": 50.0, "phone": 0.5, "scale": 348.0}),
    ("day four: the phone sync is down too", 72, {"wearable": 74.0, "phone": "down", "scale": 372.0}),
    ("day five: both record again", 96, {"wearable": 0.5, "phone": 0.5, "scale": 396.0}),
    ("day six: the wearable went quiet again", 120, {"wearable": 30.0, "phone": 0.5, "scale": 420.0}),
]


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        st = root / "state"
        st.mkdir()
        (root / "config.json").write_text(json.dumps(CFG))
        env = {"LIMITLESS_CONFIG": str(root / "config.json"), "LIMITLESS_AUDIT": str(root / "audit.jsonl")}
        now = NOW
        for title, hours, ages in STEPS:
            now = NOW + hours * H
            (st / "inputs.json").write_text(json.dumps({"at": iso(now), "ageHours": ages}))
            text = jobs_runner.brief_outage(st, now, env, root)
            if text:
                jobs_runner.brief_outage_told(st, now, env, root)
            tool = outage.tool(st, now, CFG)["value"]["label"]
            print(f"{title}")
            print(f"  brief line: {text or '(none)'}")
            print(f"  limitless_outages: {tool}")
            mark = json.loads((st / outage.MARK_FILE).read_text()) if (st / outage.MARK_FILE).exists() else {}
            print(f"  outage.json keys: since={sorted(mark.get('since', {}))} told={sorted(mark.get('told', {}))}")
        print("off (input_outage false)")
        off = {"input_outage": False}
        (root / "config.json").write_text(json.dumps(off))
        print(f"  brief line: {jobs_runner.brief_outage(st, now, env, root) or '(none)'}")
        print(f"  limitless_outages: {outage.tool(st, now, off)['value']['label']}")


if __name__ == "__main__":
    main()
