"""The synthetic weekly target example in docs/weekly-target.md: python3 -I scripts/weekly_target_example.py

Synthetic check-ins in a temporary state dir; reads no real state, writes nothing else, sends nothing.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from limitless import card, jobs, jobs_runner, tools, weekly_target  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 2_000_000_000.0                      # an arbitrary epoch; only differences matter
TODAY = datetime.fromtimestamp(NOW, timezone.utc).date()
START = TODAY - timedelta(days=5)          # today is day six of the week
WORDS = ["Done", "No", "Done", None, "Skipped", "Done"]   # None: no answer that day
checkins = {(START + timedelta(days=i)).isoformat(): w for i, w in enumerate(WORDS) if w}

print("progress, default target (four of seven):")
print(" ", weekly_target.progress(checkins, START, TODAY))
print("progress, habit_target_days 3:")
print(" ", weekly_target.progress(checkins, START, TODAY, target_days=3))
print("progress, the day after day seven:")
print(" ", weekly_target.progress(checkins, START, START + timedelta(days=7)))
print("progress, no habit week started:")
print(" ", weekly_target.progress(checkins, None, TODAY))

with tempfile.TemporaryDirectory() as d:
    st = Path(d)
    habit = {"habit": "Synthetic habit", "week_of": START.isoformat(), "checkins": checkins}
    (st / "habit.json").write_text(json.dumps(habit))
    env = {"LIMITLESS_CONFIG": str(st / "no-config.json"), "LIMITLESS_STATE": str(st)}
    print("limitless_habit value['target']:")
    print(" ", tools.habit(StateReader(st), NOW, TODAY, env)["value"]["target"])
    print("state card habit line:")
    print(" ", [ln for ln in card.build(StateReader(st), NOW, TODAY, env=env)["lines"] if ln.startswith("habit")][0])
    (st / "config.json").write_text(json.dumps({"habit_target_days": 3}))
    env3 = dict(env, LIMITLESS_CONFIG=str(st / "config.json"))
    print("state card habit line, habit_target_days 3:")
    print(" ", [ln for ln in card.build(StateReader(st), NOW, TODAY, env=env3)["lines"] if ln.startswith("habit")][0])
    print("habit check-in (default target, then habit_target_days 3):")
    print("  " + jobs_runner.body(jobs.HABIT_CHECKIN, habit).replace("\n", "\n  "))
    print("  --")
    print("  " + jobs_runner.body(jobs.HABIT_CHECKIN, habit, target_days=3).replace("\n", "\n  "))
    print("week review (default target, then habit_target_days 3):")
    print("  " + jobs_runner.body(jobs.WEEK_REVIEW, habit).replace("\n", "\n  "))
    print("  --")
    print("  " + jobs_runner.body(jobs.WEEK_REVIEW, habit, target_days=3).replace("\n", "\n  "))
