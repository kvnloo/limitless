# Stop rule and the weekly loop row

The week review keeps the one habit or drops it. The stop rule is a rule the person picks before the
week begins, so the review is not decided by mood at the end of the week. The rule only suggests. The
person's `Keep` or `Drop` reply decides, every time.

Every decided week leaves one row in the prediction ledger: the habit, the prediction, the outcome, what the
rule said and the decision. That row closes the loop: observe, make one small change, lock a prediction,
read the outcome, decide.

## The rules

You pick one when the week starts: `bin/limitless-habit-start "<habit>" --stop-rule <id> --write`, or
`limitless_habit` with `start`, `stop_rule` and `confirm: true`. It is stored as `stop_rule` in `habit.json`,
next to `week_of`, by the same atomic 0600 write that starts the week. There are no free-text rules and no
clock times, and the person never sees a number. What "most" means lives in code: more than half of the
logged days.

| id | wording | verdict |
|----|---------|---------|
| `most_done` | drop it unless most logged days were Done | keep when Done is more than half of the Done + No days, else drop |
| `any_done` | keep it if any logged day was Done | keep with at least one Done, else drop |
| `not_a_chore` | keep it unless it felt like a chore | keep (only the person can say whether it felt like a chore, so that is the reply) |
| `no_rule` | no rule: decide at the review | your call |

`stop_rule.verdict(habit_week, rule)` returns `keep`, `drop`, `your call` or `unknown`. Only Done and No
count as answers. A Skipped day, or a day with no answer, is unlogged and never counts against the habit.
The verdict is `unknown` (never `drop`) when the week has no Done or No answer at all, when no week was
started, or when no rule from the list was set.

## The week review line

`jobs_runner.week_rule` adds one line just before `Reply: Keep / Drop`. The line goes through
`tier_audit.gate` (hook `week_review:stop_rule`) and has no digits:

- `Your rule says: keep it`
- `Your rule says: drop it`
- `Your rule says: your call`

When the verdict is `unknown` there is no line, and the review looks exactly as it did before this change.

## The loop row

After the person replies Keep or Drop (`habit_replies.decide`, not a dry run), `stop_rule.record_loop`
appends one row to `predictions.jsonl`, the existing append-only ledger (there is no second store):

    {kind: "loop", week_of, habit, prediction: "prediction locked" | "none",
     outcome: supports | contradicts | inconclusive | "unknown", outcome_modality, outcome_at,
     rule, verdict, decision: Keep | Drop, decided_at, at}

Nothing is written before the reply, and a dry run writes nothing. A week that already has a loop row never
gets a second one. The outcome is the receipt as it stood when the person replied. A receipt can only be
written after day seven, so a decision made on day seven usually records `unknown`. A receipt written later
goes into the ledger next to the loop row, and the loop row is not rewritten.

`limitless_loop` (read-only) shows the last four rows, newest first, in T1 words. The `decision` is an
envelope with modality `self_report`. The `outcome` is an envelope with the receipt's own modality
(`self_report` for logged days, or whatever the state metric's digest rows name), or missing with a reason.

## Synthetic example (real output)

Made with a temp state dir and a fake push at a fixed synthetic clock. The answers were Done, Skipped, Done,
No, Done. The Skipped day stays out, so the rule sees three Done out of four logged days:

    $ start_week(..., stop_rule='most_done')
    started: Synthetic habit for the week of 2033-05-12 | stop_rule: most_done -> drop it unless most logged days were Done

    $ week review body (fake push)
    Synthetic habit: 3 of 4 logged days this week.
    habit: on the way
    Your rule says: keep it
    Reply: Keep / Drop

    $ before the reply: predictions.jsonl exists? False
    $ decide([Keep]) -> write Keep

    $ loop rows after deciding twice: 1
    {"kind": "loop", "habit": "Synthetic habit", "prediction": "none", "outcome": "unknown", "rule": "most_done", "verdict": "keep", "decision": "Keep"}

    $ limitless_loop
    {"value": {"weeks": [{"week": "this week", "habit": "Synthetic habit", "prediction": "no prediction",
      "rule": "your rule said keep it",
      "outcome": {"value": null, "modality": null, "age_h": null, "evidence_tier": "none",
                  "reason": "no prediction was locked for that week"},
      "decision": {"value": "kept", "modality": "self_report", "age_h": 0.8, "evidence_tier": "direct",
                   "label": {"label": "kept", "tier": "T1", "modality": "self_report"}}}]},
     "modality": "self_report", "age_h": 0.8, "evidence_tier": "direct",
     "label": {"label": "latest week: kept", "tier": "T1", "modality": "self_report"}}

(The tool's JSON is printed with `indent=2`. It is folded here, and nothing else is changed.)

What this does not do: it takes no action on its own (the rule suggests and the person decides). It keeps
no score and no streak, uses no clock-time rule, and gives no health or dosing advice.
