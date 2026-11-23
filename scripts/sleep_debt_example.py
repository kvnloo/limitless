"""The synthetic sleep debt example in docs/sleep-debt.md: python3 -I scripts/sleep_debt_example.py

Made-up nights in a temporary state dir; reads no real state, writes nothing else, sends nothing.
UTC stands in for the local zone.
"""
import json
import os
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from limitless import card, sleep_debt, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

UTC = timezone.utc
TODAY = date(2030, 1, 28)
NOW = datetime.combine(TODAY, time(9), UTC).timestamp()
H = 3600
SPAN = sleep_debt.RECENT_NIGHTS + sleep_debt.BASELINE_NIGHTS


def night(ago):
    return (TODAY - timedelta(days=ago)).isoformat()


def wear(ago, hours):
    return {"night": night(ago), "asleep_s": int(hours * H), "source": "synthetic-ring"}


def screen(ago, hours):
    s = datetime.combine(TODAY - timedelta(days=ago), time(23), UTC).timestamp()
    return [{"ts": int(s * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"},
            {"ts": int((s + hours * H) * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"}]


# fourteen baseline nights around eight hours, then three recent nights; the wearable missed one baseline night
BASE = [8.0, 7.5, 8.25, 8.0, 7.75, 8.5, 8.0, 7.5, 8.0, 8.25, 7.75, 8.0, 8.0, 7.5]
CASES = {
    "recent nights near the usual": [8.0, 7.75, 8.0],
    "recent nights an hour short": [7.0, 7.0, 7.0],
    "recent nights two to three hours short": [6.0, 5.5, 5.0],
}

print(f"usual night: the median of the baseline nights; some from {sleep_debt.SOME_SHARE:.0%} short, "
      f"a lot from {sleep_debt.A_LOT_SHARE:.0%} short")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    st.mkdir()
    cfg = root / "config.json"
    cfg.write_text(json.dumps({"sleep_file": "sleep.jsonl"}))
    env = {"LIMITLESS_CONFIG": str(cfg), "LIMITLESS_STATE": str(st)}
    reader = StateReader(st)

    def run(name, recent, phone=None, missed=()):
        hours = dict(zip(range(SPAN, sleep_debt.RECENT_NIGHTS, -1), BASE))
        hours.update(zip(range(sleep_debt.RECENT_NIGHTS, 0, -1), recent))
        rows = [wear(a, h) for a, h in sorted(hours.items(), reverse=True) if a not in missed]
        (st / "sleep.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        spans = [r for a, h in (phone or {}).items() for r in screen(a, h)]
        (st / "screen-events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in spans))
        out = tools.sleep_debt(reader, NOW, TODAY, env=env, tz=UTC)
        print(f"\n{name}:")
        print(" ", json.dumps(out))
        return out

    for name, recent in CASES.items():
        run(name, recent)
    print("\nthe same short nights under the raw opt-in:")
    hours = dict(zip(range(SPAN, sleep_debt.RECENT_NIGHTS, -1), BASE))
    hours.update(zip(range(sleep_debt.RECENT_NIGHTS, 0, -1), CASES["recent nights an hour short"]))
    (st / "sleep.jsonl").write_text("".join(json.dumps(wear(a, h)) + "\n" for a, h in sorted(hours.items())))
    (st / "screen-events.jsonl").write_text("")
    print(" ", json.dumps(tools.sleep_debt(reader, NOW, TODAY, raw=True, env=env, tz=UTC)["value"]))

    run("the wearable missed last night; the phone's quiet gap stands in", [7.0, 7.0, 7.0],
        phone={1: 7.0}, missed=(1,))
    run("the wearable has last night too; its night wins over the phone's", [8.0, 8.0, 8.0], phone={1: 4.0})
    run("a gap night (neither source) is skipped, never zero (as zero it would read a lot)", [8.0, 8.0, 8.0],
        missed=(2,))

    (st / "sleep.jsonl").write_text("".join(json.dumps(wear(a, 6.0)) + "\n" for a in (3, 2, 1)))
    out = tools.sleep_debt(reader, NOW, TODAY, env=env, tz=UTC)
    print("\nonly three nights, no baseline:")
    print(" ", json.dumps(out))

    hours = dict(zip(range(SPAN, sleep_debt.RECENT_NIGHTS, -1), BASE))
    hours.update(zip(range(sleep_debt.RECENT_NIGHTS, 0, -1), CASES["recent nights two to three hours short"]))
    (st / "sleep.jsonl").write_text("".join(json.dumps(wear(a, h)) + "\n" for a, h in sorted(hours.items())))
    print("\nthe state card (pre_llm_call, no raw opt-in), with no digest or habit in this state dir:")
    for ln in card.build(reader, NOW, TODAY, env=env, peak=None, light=None)["lines"]:
        print(" ", ln)
