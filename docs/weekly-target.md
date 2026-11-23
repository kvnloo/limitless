# Weekly target

Streaks punish one missed day and make people quit. The habit week counts toward a gentle weekly target
instead: "most days". A Done day counts. A No, a Skip or a day with no answer is unlogged, not failed: it
never takes anything away, there is no streak and nothing resets.

- **What counts**: `weekly_target.progress(checkins, week_start, today, target_days=...)` reads the started
  week's Done / No / Skipped answers (a tap wins over the sync's verdict, as everywhere else) for the seven
  days of the week up to `today`. It returns `{done, logged, target, reached, label}`: `done` is the Done
  days, `logged` is Done + No (the week review's M; skipped and unlogged days stay out), `target` the Done
  days that make "most days", `reached` whether `done` is there.
- **Label** (T1, digit-free): `not started` (no Done day yet), `on the way`, `target reached this week`, or
  `week closed` from day eight on.
- **Unknown is not zero**: no started habit week (no habit.json with a habit and a valid `week_of`, or a
  `today` before it) is `None`, and `limitless_habit` has no `target` field at all.
- **`habit_target_days`** (config.json, a whole number from one to seven; default four): wording, not a
  rule. It only changes which words the person sees. It never holds, drops or sends a message, never
  starts or closes a week and never changes a check-in.

Where the words show:

- `limitless_habit`: the value gains `target` (the dict above) for the week so far. Its label is a proxy
  when the phone sync filled a day, else self-reported.
- State card: once the target is reached, the habit line ends in `; target reached this week`. Before
  that it says nothing about a target.
- Habit check-in: once reached, one line under the question, `Target reached this week.`; before that
  nothing.
- Week review: one words-only line under the "N of M logged days" line, `habit: target reached this week`
  or `habit: on the way`; nothing with no Done day (the first line already says what was logged). The
  number stays where it was.

No new job, push or event: the check-in and the week review still go out exactly as before. No score, no
points and no clock-time rule. A test scans the habit and week-review code and every rendered check-in and
review for "streak", "missed", "failed" and "broke".

## Example (synthetic)

`python3 -I scripts/weekly_target_example.py`: a week on day six with Done, No, Done, no answer, Skipped,
Done. Real output:

```
progress, default target (four of seven):
  {'done': 3, 'logged': 4, 'target': 4, 'reached': False, 'label': {'label': 'on the way', 'tier': 'T1', 'modality': 'self_report'}}
progress, habit_target_days 3:
  {'done': 3, 'logged': 4, 'target': 3, 'reached': True, 'label': {'label': 'target reached this week', 'tier': 'T1', 'modality': 'self_report'}}
progress, the day after day seven:
  {'done': 3, 'logged': 4, 'target': 4, 'reached': False, 'label': {'label': 'week closed', 'tier': 'T1', 'modality': 'self_report'}}
progress, no habit week started:
  None
limitless_habit value['target']:
  {'done': 3, 'logged': 4, 'target': 4, 'reached': False, 'label': {'label': 'on the way', 'tier': 'T1', 'modality': 'self_report'}}
state card habit line:
  habit this week: Synthetic habit; today Done
state card habit line, habit_target_days 3:
  habit this week: Synthetic habit; today Done; target reached this week
habit check-in (default target, then habit_target_days 3):
  Did you do it today: Synthetic habit?
  Reply: Done / No / Skip
  --
  Did you do it today: Synthetic habit?
  Target reached this week.
  Reply: Done / No / Skip
week review (default target, then habit_target_days 3):
  Synthetic habit: 3 of 4 logged days this week.
  habit: on the way
  Reply: Keep / Drop
  --
  Synthetic habit: 3 of 4 logged days this week.
  habit: target reached this week
  Reply: Keep / Drop
```
