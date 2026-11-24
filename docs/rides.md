# Bike rides

The person's own REHIT (reduced-exertion high-intensity) bike app logs each ride as an exercise session in
the phone's health store; an export of those sessions lands in the state dir. The weekly review says in
words whether rides happened. Heart rate, power and every other raw field are tier T0: the reader never
reads them, and a cloud model sees the T1 words only (`limitless/rides.py`).

- **Where**: config.json key `rides_file` (a relative path is in the state dir). None by default. Rows:
  `{"start": "ISO-8601 with offset", "duration_s": number, "kind": "...", "source": "..."}`. Only kinds in
  `ride_kinds` (config, default `["biking_stationary", "rehit", "ride"]`) are rides. A row without a start
  with an offset, a duration over zero and a source, a start whose date is after today, or a second row with
  the same start and source, is skipped (`StateReader.ride_rows()`); the reader never raises and never writes.
- **CAROL rides**: `bin/limitless-import-fit` appends one `ride` row per CAROL FIT export to this same file
  ([carol-fit-import.md](carol-fit-import.md)).
- **Week**: today and the six days before against the seven days before that; a ride's day is its start's
  date in its own offset. Words: `rides this week: none | one | two | a few`, then `same as last week`,
  `more than last week` or `fewer than last week`. No target, no score, no streak: a week with no ride is
  `none`, never "missed".
- **Tool** `limitless_rides`: an envelope whose value is the two counts and the label, modality
  `measured`, aged by the file's mtime. Total minutes appear only with `LIMITLESS_RAW_IN_PROMPT=1` (the
  card's opt-in). No file or no ride row is `value: null` with a reason: unknown, not zero. tier_audit logs
  the label like any other tool result.
- **Week review**: one digit-free line after the body line, e.g. `Rides this week: two, more than last
  week.` No file or no ride row adds no line. The state card does not change.

Synthetic example (made-up rows, today 2030-01-28):

```
{"start": "2030-01-17T07:10:00+01:00", "duration_s": 540, "kind": "rehit", "source": "synthetic-bike-app"}
{"start": "2030-01-23T18:30:00+01:00", "duration_s": 600, "kind": "rehit", "source": "synthetic-bike-app"}
{"start": "2030-01-23T18:30:00+01:00", "duration_s": 600, "kind": "rehit", "source": "synthetic-bike-app"}
{"start": "2030-01-24T12:00:00+01:00", "duration_s": 1800, "kind": "walking", "source": "synthetic-phone"}
{"start": "2030-01-26T07:05:00+01:00", "duration_s": 570, "kind": "biking_stationary", "source": "synthetic-bike-app"}
```

The duplicate and the walk are dropped. `limitless_rides` returns
`{"value": {"this_week": 2, "last_week": 1, "label": "rides this week: two, more than last week"},
"modality": "measured", ...}`.

A count in words only: no goal, no training plan, no dosing or supplement advice, no clock-time rule.
Nothing here sends.
