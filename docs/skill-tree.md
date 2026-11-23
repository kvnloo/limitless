# Skill tree: where you are, in words

The Training Facility stacks four layers: Foundation (sleep, energy, nutrition, recovery), then Learning,
then Flow, then Enhancement. Foundation comes first. The skill tree shows which layer the person is in and
what happened to each habit, in plain words. It never shows a score, a level, a percent, XP or a streak.

`limitless/skill_tree.py` is pure. It keeps no record of its own and adds no ledger:

- the habits are the habit catalogue's (`habit_catalogue.CATALOGUE`, grouped by `layer`;
  [docs/habit-catalogue.md](habit-catalogue.md)). The catalogue has no Enhancement habit yet, so that layer
  is listed with none;
- the decisions are the weekly loop rows in `predictions.jsonl` (`stop_rule.loop_rows`, read through
  `habit_catalogue.decisions`: the latest Keep or Drop for each habit wins);
- this week's habit is `habit.json`'s `habit`, only while its week runs (`jobs.habit_week_gate`).

## One word per habit

| state | when |
|---|---|
| `trying` | it is this week's habit (this wins, even over an earlier Drop) |
| `kept` | the latest decision for it is Keep |
| `dropped` | the latest decision for it is Drop |
| `not tried` | anything else |

A week with no Keep or Drop (skipped, or never decided) is unlogged, never a drop. A record the code can't
read (a torn line, a decision that is not Keep or Drop, a habit not on the list) also counts as `not tried`,
never `dropped`.

## Open or later

A layer is open when it is Foundation, or when every earlier layer has at least one kept habit. Otherwise it
is later. Trying or dropping a habit opens nothing. A kept habit in a later layer is still shown as kept,
but it does not open anything past an earlier layer with no kept habit.

## The tool: `limitless_skill_tree`

Read-only. The value is `{layers: [{name, open, habits: [{name, state}]}]}`, with the four layers in order.
Modality is `derived`, `age_h` is null, and `evidence_tier` is the tier of the newest self-reported Keep or
Drop (`none` before any week was decided). The label is a digit-free T1 label of the form
`<last open layer> open, <how many habits are kept, in words> kept`, for example
`Foundation open, one habit kept`. It only suggests, and it never starts a habit: starting one still needs
the person to say start habit, and then `limitless_habit` start with their yes. Nothing is written, sent or
scheduled. There is no push and no job.

## The card: `limitless_card_view` kind `skill_tree`

The same tree as one self-contained HTML card through `ui_card` ([docs/ui-card.md](ui-card.md)), one row per
layer (`skill_tree.lines`). An open layer's row gets a known chip. A later layer's row says it is waiting
for a kept habit in every earlier layer, so it gets a held chip. Every row goes through `tier_audit.gate`
with the raw opt-in off, so a row with a digit would be dropped and counted. The card uses inline CSS and
no JavaScript. It is written (0600, named by its content hash) only when config `card_dir` or
`LIMITLESS_CARD_DIR` is set. Otherwise it is only rendered, and the result carries a note. The label is
`a skill tree card with four rows`.

## Synthetic example (real output)

A temp state dir holds three synthetic weeks: the first habit kept, the second dropped, and the third
running this week. The clock is fixed. The commands are `python3 -I scripts/skill_tree_example.py --print`,
and `python3 -I scripts/skill_tree_example.py` to write the committed card,
[examples/skill-tree.html](examples/skill-tree.html):

```
## limitless_skill_tree: value.layers, one per line
{"name": "Foundation", "open": true, "habits": [{"name": "Feeds-free first hour", "state": "kept"}, {"name": "Daylight after waking", "state": "dropped"}, {"name": "Lights down at wind-down", "state": "trying"}, {"name": "Phone sleeps outside the bedroom", "state": "not tried"}, {"name": "Stand up after a long block", "state": "not tried"}, {"name": "An easy ride", "state": "not tried"}]}
{"name": "Learning", "open": true, "habits": [{"name": "A short review after focus", "state": "not tried"}]}
{"name": "Flow", "open": false, "habits": [{"name": "Next step before the break", "state": "not tried"}]}
{"name": "Enhancement", "open": false, "habits": []}
## limitless_skill_tree: the rest of the envelope
{
  "modality": "derived",
  "age_h": null,
  "evidence_tier": "stale",
  "label": {
    "label": "Learning open, one habit kept",
    "tier": "T1",
    "modality": "derived"
  },
  "note": "read-only and a suggestion only: it never starts a habit; a week with no Keep or Drop is unlogged, never a drop"
}
## limitless_card_view kind skill_tree
{
  "value": {
    "path": "<card dir>/card-ef696d502a58e652.html",
    "rows": 4,
    "dropped": 0
  },
  "modality": "derived",
  "age_h": null,
  "evidence_tier": "stale",
  "label": {
    "label": "a skill tree card with four rows",
    "tier": "T1",
    "modality": "derived"
  }
}
## the card's rows (chip, then text)
[known] Foundation open: Feeds-free first hour kept; Daylight after waking dropped; Lights down at wind-down trying; Phone sleeps outside the bedroom not tried; Stand up after a long block not tried; An easy ride not tried
[known] Learning open: A short review after focus not tried
[held] Flow later, waiting for a kept habit in every earlier layer: Next step before the break not tried
[held] Enhancement later, waiting for a kept habit in every earlier layer: no habits on the list yet
```

It never shows a score, level, XP, streak or capability number: no score anywhere, and counts are given in
words. A skipped week is unlogged. Nothing is sent, pushed or scheduled. It never starts a habit on its own.
