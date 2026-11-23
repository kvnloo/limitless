# Experiments: a locked prediction, a stated falsifier and a lagged outcome

The ask (D12): N-of-1 habit experiments. The prediction is fixed before the habit week, the person can say in
their own words what result would show it wrong (the falsifier), and an effect that shows late can be judged a
week or two after the habit week instead of on it. One read-only tool shows all of it. Habits only: a
prediction about anything taken is refused at lock time.

## The record

There is one record, `predictions.jsonl` in the state dir, append-only: a row is never rewritten
(`limitless/prediction.py`, the same ledger the stop rule's loop rows go to).

- `prediction.lock(state_dir, week_of, text, metric, direction, falsifier=None, lag_days=0)` writes one
  prediction row per habit week, `{kind: "prediction", week_of, text, metric, direction, falsifier, lag_days,
  locked_at}`, only with confirm (`limitless_habit` with `predict` and `confirm: true` after the person said
  yes; without it the result says what would be locked and nothing is written).
- `falsifier` is optional plain words; blank is none. `lag_days` is one of a short fixed list: none (the habit
  week itself), one week or two weeks. A lag needs a state metric (sleep or readiness): logged days are the
  habit itself and are judged on its own week. A row from before these fields reads as no falsifier, no lag.
- `prediction.receipt(state_dir, week_of)` judges the locked prediction once, writing one receipt row only
  with confirm (`limitless_habit` with `receipt` and `confirm: true`). With no lag it comes after day seven, as
  before. With a lag the result is `pending` (the verdict is pending, the reason is plain words, nothing is
  written) until the lagged span is over; then the outcome is the state metric over the seven days that many
  days after the habit week's start, against the seven days before the habit week. Fewer than three logged
  habit days in the week, or fewer than three days with the metric in the judged span or the week before, is
  `inconclusive`, never a guess. The lag stays on the prediction row; the receipt row has no digit beyond its
  dates.

## The view

`limitless_experiment` (read-only) returns `{value: {current, past}, modality: "derived", age_h,
evidence_tier}` with a digit-free T1 label:

- `current` is words for the newest prediction with no receipt: "one experiment running, outcome pending"
  while its habit week is on, "one experiment waiting, outcome pending (judged later)" while a lag has not
  passed, "one experiment ready to judge" once it is due; then whether a falsifier was stated and the lagged
  span in words. With nothing locked it is "no experiment locked"; with every prediction judged, "no
  experiment running".
- `past` is every other locked week, newest first, as `{week_of, verdict, falsifier_stated}`. The verdict is the
  receipt's (supports, contradicts, inconclusive), else pending or not judged.
- `age_h` is the age of the newest prediction or receipt row; evidence_tier is that of a self-report of that
  age, none before anything is locked.
- `strength` (beside the envelope, once anything is locked) is the newest prediction's habit on the evidence
  ladder in words, for example "preregistered: one locked week supported it"
  ([evidence-ladder.md](evidence-ladder.md)).
- The prediction text and the falsifier text are the person's own words (T0). They appear only with the raw
  opt-in, `LIMITLESS_RAW_IN_PROMPT=1`, like the other tools' raw fields.

## The week review

On day seven, when the habit week's prediction has a lag, the week review gains one line before the stop
rule's: "Experiment: outcome pending (judged later)", through `tier_audit.gate` (hook
`week_review:experiment`). Otherwise the review is unchanged.

## What it never does

No score, no streak, no clock time. It never locks, judges or starts anything by itself: it only suggests,
and a prediction or receipt is written only with confirm after the person's yes. It refuses predictions about
anything taken; it is for habits. Nothing is sent: no push, no job, no schedule card.

## A synthetic example

`python3 -I scripts/experiment_example.py`: a temporary state dir with one synthetic habit week and synthetic
sleep rows, a fixed clock moved day by day. Its real output:

```text
$ day 0: limitless_experiment {}
{"age_h": null, "evidence_tier": "none", "label": {"label": "no experiment locked", "modality": "derived", "tier": "T1"}, "modality": "derived", "note": "read-only and a suggestion only: a prediction is locked only through limitless_habit predict after the person said yes in this turn; a receipt only through limitless_habit receipt", "value": {"current": "no experiment locked", "past": []}}
$ day 0: limitless_habit {"predict": "Synthetic: no screens after the wind-down event, and sleep comes out longer a week later", "metric": "sleep_h", "direction": "up", "falsifier": "Synthetic: sleep in the week after is no longer than in the week before", "lag_days": 7}
{"age_h": 0.0, "evidence_tier": "direct", "label": {"label": "would lock this prediction", "modality": "self_report", "tier": "T1"}, "modality": "self_report", "value": {"action": "would lock", "prediction": {"direction": "up", "falsifier": "Synthetic: sleep in the week after is no longer than in the week before", "kind": "prediction", "lag_days": 7, "locked_at": "2030-01-15T12:00:00+00:00", "metric": "sleep_h", "text": "Synthetic: no screens after the wind-down event, and sleep comes out longer a week later", "week_of": "2030-01-15"}, "reason": "dry run: nothing written"}}
$ day 0: limitless_habit {"predict": "Synthetic: no screens after the wind-down event, and sleep comes out longer a week later", "metric": "sleep_h", "direction": "up", "falsifier": "Synthetic: sleep in the week after is no longer than in the week before", "lag_days": 7, "confirm": true}
{"age_h": 0.0, "evidence_tier": "direct", "label": {"label": "locked this prediction", "modality": "self_report", "tier": "T1"}, "modality": "self_report", "value": {"action": "locked", "prediction": {"direction": "up", "falsifier": "Synthetic: sleep in the week after is no longer than in the week before", "kind": "prediction", "lag_days": 7, "locked_at": "2030-01-15T12:00:00+00:00", "metric": "sleep_h", "text": "Synthetic: no screens after the wind-down event, and sleep comes out longer a week later", "week_of": "2030-01-15"}, "reason": "prediction locked: it is never rewritten"}}
$ day 2: limitless_experiment {}
{"age_h": 48.0, "evidence_tier": "stale", "label": {"label": "one experiment running, outcome pending", "modality": "derived", "tier": "T1"}, "modality": "derived", "note": "read-only and a suggestion only: a prediction is locked only through limitless_habit predict after the person said yes in this turn; a receipt only through limitless_habit receipt", "strength": {"rung": null, "why": "nothing measured, judged or cited", "words": "no evidence yet"}, "value": {"current": "one experiment running, outcome pending; falsifier stated; outcome judged on the week after the habit week", "past": []}}
$ day 6: the week review's lines
Synthetic habit: screens off at the wind-down event: 5 of 6 logged days this week.
habit: target reached this week
Experiment: outcome pending (judged later)
Reply: Keep / Drop
$ day 9: limitless_habit {"receipt": true, "confirm": true}
{"age_h": 0.0, "evidence_tier": "direct", "label": {"label": "outcome pending: judged later", "modality": "self_report", "tier": "T1"}, "modality": "self_report", "value": {"action": "pending", "reason": "the outcome is judged later, once the week after the habit week is over: nothing written", "receipt": null, "verdict": "pending"}}
$ day 9: limitless_experiment {}
{"age_h": 216.0, "evidence_tier": "stale", "label": {"label": "one experiment waiting, outcome pending (judged later)", "modality": "derived", "tier": "T1"}, "modality": "derived", "note": "read-only and a suggestion only: a prediction is locked only through limitless_habit predict after the person said yes in this turn; a receipt only through limitless_habit receipt", "strength": {"rung": null, "why": "nothing measured, judged or cited", "words": "no evidence yet"}, "value": {"current": "one experiment waiting, outcome pending (judged later); falsifier stated; outcome judged on the week after the habit week", "past": []}}
$ day 14: limitless_habit {"receipt": true, "confirm": true}
{"age_h": 0.0, "evidence_tier": "direct", "label": {"label": "wrote this receipt: supports", "modality": "self_report", "tier": "T1"}, "modality": "self_report", "value": {"action": "wrote", "reason": "receipt written: it is never rewritten", "receipt": {"at": "2030-01-29T12:00:00+00:00", "kind": "receipt", "locked_at": "2030-01-15T12:00:00+00:00", "outcome": "higher", "reason": "sleep_h was higher in the week after the habit week than the week before", "verdict": "supports", "week_of": "2030-01-15"}}}
$ day 14: limitless_experiment {}
{"age_h": 0.0, "evidence_tier": "direct", "label": {"label": "no experiment running", "modality": "derived", "tier": "T1"}, "modality": "derived", "note": "read-only and a suggestion only: a prediction is locked only through limitless_habit predict after the person said yes in this turn; a receipt only through limitless_habit receipt", "strength": {"rung": "preregistered", "why": "a prediction locked before the week, and its outcome receipt supported it", "words": "preregistered: one locked week supported it"}, "value": {"current": "no experiment running", "past": [{"falsifier_stated": true, "verdict": "supports", "week_of": "2030-01-15"}]}}
$ day 14: limitless_experiment {} (LIMITLESS_RAW_IN_PROMPT=1)
{"age_h": 0.0, "evidence_tier": "direct", "label": {"label": "no experiment running", "modality": "derived", "tier": "T1"}, "modality": "derived", "note": "read-only and a suggestion only: a prediction is locked only through limitless_habit predict after the person said yes in this turn; a receipt only through limitless_habit receipt", "strength": {"rung": "preregistered", "why": "a prediction locked before the week, and its outcome receipt supported it", "words": "preregistered: one locked week supported it"}, "value": {"current": "no experiment running", "past": [{"falsifier": "Synthetic: sleep in the week after is no longer than in the week before", "falsifier_stated": true, "text": "Synthetic: no screens after the wind-down event, and sleep comes out longer a week later", "verdict": "supports", "week_of": "2030-01-15"}]}}
```
