# Habit catalogue: the next habit to offer, one a week

One habit a week, Foundation (sleep, energy, recovery) first. When a week ends with Drop, or before the first
week, the agent offers the next habit from a short fixed list instead of inventing one. Few good habits, not
many goals.

`limitless/habit_catalogue.py` is pure: the list, `next_habit` and the review line. It keeps no habit store of
its own: a started habit lives in `habit.json` (`habit_start.start_week`), and decided weeks are the loop rows
in `predictions.jsonl` (`stop_rule.record_loop`).

## The list

Ordered by layer (foundation, then learning, then flow) and, inside a layer, easiest first. The first entry is
the existing week-one habit on its existing cue (`habit_cue`, an hour after the wake). Every cue is an event
from `jobs.EVENTS`, never a clock time; `start` is a first step of two minutes or less.

| id | layer | name | cue | start | environment |
|---|---|---|---|---|---|
| `feeds_free_first_hour` | foundation | Feeds-free first hour | `habit_cue` | after you wake, put the phone face down and do one thing that is not a feed | phone charging away from the bed |
| `daylight_after_wake` | foundation | Daylight after waking | `wake` | open the curtains and stand by the window for a moment | curtains left half open |
| `lights_down_at_wind_down` | foundation | Lights down at wind-down | `wind_down` | switch off the big light and turn on one lamp | a lamp by the couch |
| `phone_sleeps_outside` | foundation | Phone sleeps outside the bedroom | `sleep_mode_on` | put the phone on a charger outside the bedroom | a charger in the hall |
| `stand_after_long_block` | foundation | Stand up after a long block | `long_block` | stand up and walk to the window and back | a water glass across the room |
| `easy_ride` | foundation | An easy ride | `focus_end` | put on your riding shoes and sit on the bike | bike in view |
| `short_review_after_focus` | learning | A short review after focus | `focus_end` | open your review deck and answer one card | the deck one tap away |
| `next_step_before_break` | flow | Next step before the break | `focus_end` | write the first step of the next block on a note | a notepad beside the keyboard |

A test fails if an entry has a digit, a clock time, a drug, supplement, caffeine or dosing word, or a cue
that is not an event (`habit_catalogue.problems`). At most eight entries.

## Which one comes next

`next_habit(loop_rows, current=None)`:

- a habit whose latest decision is Keep is never offered again;
- the running habit (`current`: habit.json while its week runs) is not offered;
- untried habits come first, in list order;
- a dropped habit comes back only after every other one has been tried;
- when every habit is kept or running, the answer is none, with a plain reason.

A week with no loop row (skipped, or never decided) is unlogged, never a drop. A habit not on the list
(a person's own words) is left alone.

## The tool: `limitless_habit_next`

Read-only. The value is `{id, name, cue, start}`; modality `derived`, `age_h` null, `evidence_tier` that of
the newest self-reported decision it used (`none` before any week was decided), a digit-free T1 label
`next habit: <name>`, `because` in words and `habit_week` (running or not running). It only suggests:
starting the habit still needs the person to say start habit, and then `limitless_habit` with `start` and
`confirm: true` (the existing `habit_start` path, which refuses while a week runs). Nothing is written, sent
or started.

## After a Drop

When `bin/limitless-habit-ingest` logs a Drop reply to the week review (or would, in a dry run), it prints one
more line, `Next up, if you want it: <name>.` (`jobs_runner.week_next`, through `tier_audit.gate`, hook
`week_review:next`). Nothing after Keep, nothing when the decision is unknown, nothing when the list is
exhausted. There is no new push and no new job.

## The circuit breaker (feed reflex)

One more entry sits outside the ordered list: `CIRCUIT_BREAKER`, "Circuit breaker after unlocking" (cue
`habit_cue`; start: when a feed opens straight after unlocking, close it and name one thing you came to do). It is
offered only when the feed reflex ([feed-reflex.md](feed-reflex.md)) says a feed was often the first thing opened
after unlocking, the feeds-free first hour is not running, and the person has not run, kept or dropped it yet.
Then `limitless_habit_next` and the `Next up` line after a Drop name it first. Otherwise the list and its order are
unchanged. It only suggests: nothing starts without the person's yes.

## Synthetic example (real output)

A temp state dir with nothing in it, then one dropped week of the first habit
(`python3 -I` on a script calling the plugin handler with the clock fixed):

```
## before the first week
{
  "value": {
    "id": "feeds_free_first_hour",
    "name": "Feeds-free first hour",
    "cue": "habit_cue",
    "start": "after you wake, put the phone face down and do one thing that is not a feed"
  },
  "modality": "derived",
  "age_h": null,
  "evidence_tier": "none",
  "because": "the first habit on the list not tried yet",
  "label": {
    "label": "next habit: Feeds-free first hour",
    "tier": "T1",
    "modality": "derived"
  },
  "habit_week": "not running",
  "note": "a suggestion only: nothing was started; the person starts it by saying start habit, and then limitless_habit start runs with their yes"
}
## the week review line after a Drop
'Next up, if you want it: Daylight after waking.'
## after Keep
''
## after that week was dropped
{
  "value": {
    "id": "daylight_after_wake",
    "name": "Daylight after waking",
    "cue": "wake",
    "start": "open the curtains and stand by the window for a moment"
  },
  "modality": "derived",
  "age_h": null,
  "evidence_tier": "stale",
  "because": "the next habit on the list not tried yet",
  "label": {
    "label": "next habit: Daylight after waking",
    "tier": "T1",
    "modality": "derived"
  },
  "habit_week": "not running",
  "note": "a suggestion only: nothing was started; the person starts it by saying start habit, and then limitless_habit start runs with their yes"
}
```

Never: streaks or scores, clock times, drug, supplement, caffeine or dosing content, more than one habit a
week, or starting a habit by itself.
