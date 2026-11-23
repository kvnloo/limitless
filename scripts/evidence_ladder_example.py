"""The synthetic evidence-ladder example in docs/evidence-ladder.md: python3 -I scripts/evidence_ladder_example.py

Part one prints strength.strength_of for one small synthetic claim per rung. Part two builds a temporary state
dir with one synthetic habit and three habit weeks, each with a prediction locked before it (logged days, at
least four of seven) and its receipt after day seven through prediction.lock / prediction.receipt, and reads the
habit's rung after each week from the ledger, then the ``strength`` key of limitless_experiment and
limitless_loop. Reads no real state, writes nothing outside the temporary dir, sends nothing.
"""
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import prediction, stop_rule, strength, tools  # noqa: E402

NOW = 1894708800.0                  # 2030-01-15 at noon UTC
FIRST = date(2030, 1, 15)
HABIT = "Synthetic walk after lunch"
WEEKS = (("Done", "Done", "Done", "Done", "Done", "No", "Done"),    # supports
         ("No", "No", "No", "No", "Done", "No", "No"),              # contradicts
         ("Done", "No", "Done", "Done", "Done", "Done", None))       # supports

CLAIMS = (
    ("one reading", {"readings": 1}),
    ("a weekly average", {"readings": 7, "computed": True}),
    ("seen together on logged days", {"readings": 7, "computed": True, "days": 7}),
    ("one locked week supported", {"weeks": [{"week_of": "2030-01-15", "locked": True, "verdict": "supports",
                                              "logged_days": 6}]}),
    ("two locked weeks supported", {"weeks": [{"week_of": w, "locked": True, "verdict": "supports",
                                               "logged_days": 6} for w in ("2030-01-15", "2030-01-29")]}),
    ("contradicted twice", {"weeks": [{"week_of": w, "locked": True, "verdict": "contradicts",
                                       "logged_days": 6} for w in ("2030-01-15", "2030-01-29")]}),
    ("an outside source", {"citation": "Synthetic Journal of Habits: a replicated trial"}),
)


def main():
    print("strength_of, one synthetic claim per rung:")
    for what, claim in CLAIMS:
        s = strength.strength_of(claim)
        print(f"  {what:<30} -> {s['words']}")
    with tempfile.TemporaryDirectory() as tmp:
        st = Path(tmp)
        print("\nthe ledger, one habit, a locked prediction per week:")
        for i, answers in enumerate(WEEKS):
            start = FIRST + timedelta(days=14 * i)
            checkins = {(start + timedelta(days=d)).isoformat(): a for d, a in enumerate(answers) if a}
            h = {"habit": HABIT, "week_of": start.isoformat(), "checkins": checkins}
            (st / f"habit-{start.isoformat()}.json").write_text(json.dumps(h))
            prediction.lock(st, start.isoformat(), "Synthetic prediction: most days done", "logged",
                            "at_least 4 of 7", write=True, today=start, now=NOW)
            r = prediction.receipt(st, start.isoformat(), write=True, today=start + timedelta(days=7), now=NOW)
            stop_rule.record_loop(st, h, "Keep", (start + timedelta(days=7)).isoformat() + "T00:00:00+00:00", now=NOW)
            print(f"  week {i + 1}: receipt {r['receipt']['verdict']:<12} -> "
                  f"{strength.habit_strength(st, HABIT)['words']}")
        later, today = NOW + 50 * 86400, FIRST + timedelta(days=50)
        print("\nlimitless_experiment strength:", json.dumps(tools.experiment(st, later, today)["strength"]))
        out = tools.loop(st, later, today)
        print("limitless_loop strength:      ", json.dumps(out["strength"]))
        print("limitless_loop envelope keys: ", sorted(k for k in out if k in ("value", "modality", "age_h",
                                                                               "evidence_tier")))


if __name__ == "__main__":
    main()
