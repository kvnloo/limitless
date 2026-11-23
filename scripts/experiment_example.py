"""The synthetic experiment example in docs/experiment.md: python3 -I scripts/experiment_example.py

A temporary state dir with one synthetic habit week and synthetic sleep digest rows (the week before, the habit
week and the week after), a fixed clock moved day by day. It locks one prediction with a falsifier and a lag of
a week through the limitless_habit handler (dry run, then confirm), reads limitless_experiment as the weeks go
by, prints the week review's lines on day seven, asks for the receipt while it is pending and again once the
lag has passed, and reads the view with the raw opt-in. Reads no real state, writes nothing outside the
temporary dir, sends nothing.
"""
import json
import os
import sys
import tempfile
from datetime import date, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import jobs, jobs_runner, plugin  # noqa: E402

WEEK = date(2030, 1, 15)
NOON = 1894708800.0                # WEEK at noon UTC: the clock of day zero
TEXT = "Synthetic: no screens after the wind-down event, and sleep comes out longer a week later"
FALSIFIER = "Synthetic: sleep in the week after is no longer than in the week before"


def at(day):
    return NOON + day * 86400


def tool(name, args, env, day):
    with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=at(day)):
        out = json.loads(plugin._handler(plugin.TOOLS[name][1], name)(args))
    raw = " (LIMITLESS_RAW_IN_PROMPT=1)" if env.get("LIMITLESS_RAW_IN_PROMPT") == "1" else ""
    print(f"$ day {day}: {name} {json.dumps(args, ensure_ascii=False)}{raw}")
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return out


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    st.mkdir()
    habit = {"habit": "Synthetic habit: screens off at the wind-down event", "week_of": WEEK.isoformat(),
             "checkins": {(WEEK + timedelta(days=i)).isoformat(): a
                          for i, a in enumerate(("Done", "Done", "No", "Done", "Done", "Skipped", "Done"))}}
    (st / "habit.json").write_text(json.dumps(habit))
    sleep = {**{d: 6.5 for d in range(-7, 0)}, **{d: 6.6 for d in range(0, 7)}, **{d: 7.1 for d in range(7, 14)}}
    (st / "digests.jsonl").write_text("".join(json.dumps(
        {"date": (WEEK + timedelta(days=d)).isoformat(), "metrics": {"sleep_h": {"value": v, "modality": "proxy"}}})
        + "\n" for d, v in sleep.items()))
    env = {"LIMITLESS_STATE": str(st), "LIMITLESS_CONFIG": str(root / "none.json"), "LIMITLESS_RAW_IN_PROMPT": "0"}

    tool("limitless_experiment", {}, env, 0)
    ask = {"predict": TEXT, "metric": "sleep_h", "direction": "up", "falsifier": FALSIFIER, "lag_days": 7}
    tool("limitless_habit", ask, env, 0)
    tool("limitless_habit", dict(ask, confirm=True), env, 0)
    tool("limitless_experiment", {}, env, 2)

    print("$ day 6: the week review's lines")
    print(jobs_runner.week_review_body(st, habit, {}, env, root, timezone.utc, jobs.review_day(habit), at(6)))

    tool("limitless_habit", {"receipt": True, "confirm": True}, env, 9)
    tool("limitless_experiment", {}, env, 9)
    tool("limitless_habit", {"receipt": True, "confirm": True}, env, 14)
    tool("limitless_experiment", {}, env, 14)
    tool("limitless_experiment", {}, dict(env, LIMITLESS_RAW_IN_PROMPT="1"), 14)
