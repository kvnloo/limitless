# The habit card: one generic recurring self-check

`limitless/habit_card.py` is the habit card as a module a Hermes core reviewer can read on its own. It is
stdlib only (Python 3.9+), imports nothing else from `limitless`, holds no data and has no clock, file,
network or send. Any recurring self-check a host wants to offer ("did you do X today?", then a Keep / Drop
at the end of the week) fits it. It is the fourth upstream-shaped piece beside the decision-window gate
([decision-window.md](decision-window.md)), the send gate and the evidence envelope.

## Inputs

`HabitCard(name, cue, start_s=120)`, frozen:

| field | what it is | rejected (`ValueError`) |
|---|---|---|
| `name` | the habit in the person's words, trimmed | empty or not text |
| `cue` | the EVENT that prompts the check-in: `wake`, `wind_down`, `habit_cue`, `focus_end`, ... | anything that is not lowercase words joined by `_`: so never a clock time (`07:00`, `7am`), a cron string or `@daily` |
| `start_s` | the first step, in seconds: a start of two minutes or less | above 120, zero, negative, a float or a bool |
| `replies` | fixed: `Done`, `No`, `Skip` (`habit_card.REPLIES`) | any other set |

The card state is a mapping with one table, `checkins: {ISO day: "Done" | "No"}`. Every other key is the
host's and is carried through untouched (limitless keeps `habit`, `week_of`, `stop_rule`, `decision` there).

## Operations

- `record(card_state, day, reply)` returns a new state; the input is never changed. `Done` and `No` (any
  case, spaces around ignored) set the day's entry. `Skip` leaves the day with **no entry**: skipped is
  unlogged, not a No. Anything else (no reply, "maybe", an expired ask) leaves the table as it was.
- `week_number(card_state, week_start)` returns the one day-seven number for the seven days from
  `week_start`: `{done, logged, unknown}`. `done` is the Done days, `logged` the Done + No days, `unknown` the
  days with no entry (skipped, unanswered or never asked). `logged + unknown` is always seven. No valid
  `week_start` is `None`: no week, never zero.
- `verdict_inputs(card_state, week_start, rule=None)` returns what a Keep / Drop rule reads:
  `{done, logged, unknown, rule, decisions: ("Keep", "Drop")}`, or `None` with no week. It decides nothing:
  the rule lives with the host, and the person's Keep or Drop reply decides, always.

## Unknown is not No

A day with no Done or No entry is unknown. It is never counted as a No, never shown as a failure and never
the denominator of a rate. The week `Done, Done, (nothing), No, Skip, (nothing), Done` is done three, logged
four, unknown three: one No, not "four of seven failed", and no rate over seven.
`tests/test_habit_card_unknown_not_no.py` is that contract.

## No clock times, no score

The cue is an event the host already detects. The card cannot carry a time of day, so it cannot become a
fixed-hour reminder. There is no score, no rate, no streak and no level: the only numbers are the three
counts, and a host shows them in words if it wants to (limitless says "3 of 4 logged days").

## How limitless uses it

`jobs.record_checkin` records through `habit_card.record`. A Skip, which the card leaves with no entry, is
then marked `Skipped` in `habit.json` so the day reads as answered and a later tap never overwrites it
(first tap wins); every reader still counts it as unlogged. `jobs.week_card_state(habit, synced)` turns the
started week into a card state (a tap wins over the sync, only Done and No kept); `jobs.week_logged` reads
`week_number` from it, and `stop_rule.verdict` reads `verdict_inputs` and applies its listed rules (most
logged days Done, any Done, not a chore, no rule). No behaviour changed: every existing habit, one-tap,
passive-habit, stop-rule and day-seven test passes untouched.

## Example (synthetic)

`python3 -I scripts/habit_card_example.py`, real output:

```text
card: {"name": "Lights down", "cue": "wind_down", "start_s": 120, "replies": ["Done", "No", "Skip"]}
state: {"checkins": {"2030-01-07": "Done", "2030-01-08": "Done", "2030-01-10": "No", "2030-01-13": "Done"}}
week_number: {"done": 3, "logged": 4, "unknown": 3}
verdict_inputs: {"done": 3, "logged": 4, "unknown": 3, "rule": "most_done", "decisions": ["Keep", "Drop"]}
habit.json checkins: {"2030-01-07": "Done", "2030-01-08": "Done", "2030-01-10": "No", "2030-01-11": "Skipped", "2030-01-13": "Done"}
limitless stop rule: keep
limitless week review: Lights down: 3 of 4 logged days this week.
schedule card habit_checkin: {"name": "Habit check-in", "trigger": "wind_down", "ends": "sleep_mode_on", "answers": "Done, No or Skip in one tap; no answer stays unlogged"}
schedule card week_review: {"name": "Week review", "trigger": "wind_down", "ends": "sleep_mode_on", "answers": "Keep or Drop in one tap; no answer stays unlogged"}
```

`tests/test_habit_card_docs.py` runs the script and checks this block, so it cannot drift.

## On a #158289 Schedule card

[#158289](https://github.com/NousResearch/hermes-agent/pull/158289) shows a recurring job as a "Schedule
this job?" card. One habit card is two schedule cards on the same cue, as
[schedule-cards.md](schedule-cards.md) maps them:

| habit card | schedule card field | check-in card | day-seven card |
|---|---|---|---|
| `cue` | `trigger` (the card's `schedule` clock or cron string is on purpose not used) | the cue event | the same cue, first one from day seven |
| `name` | `name` / `description` | "Habit check-in" | "Week review" |
| `replies` / `DECISIONS` | `words.answers`, and the ask's last line `Reply: Done / No / Skip` | Done, No or Skip | Keep or Drop |
| `week_number` | the week review's body | none | "N of M logged days" (`done` of `logged`; unknown left out) |
| `start_s` | none (the habit's first step, said when the week starts) | none | none |

The card adds no field to #158289 and nothing that needs a clock. A host without schedule cards can still
use `record` and `week_number` directly.
