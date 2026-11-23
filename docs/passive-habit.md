# Passive habit days

An older loop can measure the habit passively: one row per day, from phone screen data, saying whether the
first hour after the wake was feed-free. `limitless_habit` shows those days as measured evidence, labelled
as a proxy, next to the confirmed habit week and never instead of it.

- **Where**: config.json key `passive_habit_file` (a relative path is in the state dir). None by default.
  Rows: `{"day": "YYYY-MM-DD", "wake", "feedMinFirstHour", "firstApp", "firstCat", "minToFirstFeed",
  "met": bool}`. Only `day` and `met` are read; a row without a real date and a bool `met` is skipped, and
  the last row for a day wins (`StateReader.passive_habit_days()`).
- **No confirmed week**: when the file has rows for today and the six days before, `limitless_habit`
  returns `passive: {days_measured, days_met, modality: "proxy"}` with the label
  `habit not started; phone data shows the first hour mostly feed-free`. The words come from the counts:
  mostly (at least two thirds), about half, rarely (at most one third); fewer than three measured days is
  `not enough phone data`. Nothing is written, no day counts as Done and no week starts: only
  `habit_start` (after the person said yes) starts a week.
- **Confirmed week**: `passive` covers the week's days so far and sits beside the check-ins; `days`,
  `counts` and `logged` are the tapped answers, unchanged. The week review keeps its tapped
  "N of M logged days" and adds a second line, e.g.
  `Phone data (a proxy, not a check-in): the first hour mostly feed-free.`
- **Unknown is not zero**: no file configured, a missing file or no row in the days asked about gives no
  `passive` field at all, never "0 of 0".
- **Card and catch-up**: the habit line gains the digit-free words only (e.g.
  `habit: none set this week; phone data shows the first hour mostly feed-free`).

No score and no clock-time rule: the wake is an event the older loop found. Nothing here sends.
