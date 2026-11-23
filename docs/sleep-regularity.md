# Sleep regularity: how steady sleep times have been, in words

Sleep regularity matters as much as length, and drift is easy to miss night by night. `limitless/regularity.py`
reads when each night ran over the last fourteen nights and says, in plain words, whether sleep times have been
steady, varied a lot, or drifted later or earlier. It is observation only: no bedtime, no target time, no
clock-time rule, no advice, no supplement, drug or dosing note.

- **Spans** (`sleep.timed_nights`): one `{night, wearable, proxy}` per night, each a `(start_s, end_s)` span or
  none. The wearable span comes from optional `start` and `end` fields on a `sleep_file` row (ISO-8601 or epoch
  seconds; `StateReader.sleep_rows` keeps them as `span` when both parse and the span is over zero and at most a
  day, and drops a bad pair without dropping the row). A row without them still counts for `limitless_sleep`'s
  coverage, but has no times. The phone span is the same quiet gap `sleep.nights` measures.
- **Kept apart**: the wearable and the phone estimate are read separately and never mixed. A source with fewer
  than `regularity_min_nights` spans (config, an int of at least two; default 4) is unknown, never "regular".
- **Measures** (T0, code only): the midpoint and the end (wake) of each span as a local minute of the day on a
  circle, so nights either side of midnight are minutes apart, not a day. Spread is the circular standard
  deviation. Drift is the least-squares slope of the midpoints against the date across the nights read.
- **Words** (T1, no digit, no clock time): `drifting later` / `drifting earlier` when the drift is an hour or
  more and the nights sit close to the drift line; else `sleep times vary a lot` when the midpoint or wake
  spread is over an hour; else `sleep times steady`. The source is named: `wearable: ...` when the wearable is
  known, else `phone estimate: ...`, else `unknown: too few nights ...` or `unknown: no nights ...`.
- **Tool**: `limitless_sleep` gains a `regularity` field rather than a tool of its own: it reads the same two
  sources under the same envelope, so one call says how sleep has been. Under `LIMITLESS_RAW_IN_PROMPT=1` the
  value also carries `regularity_min`, per source the nights read and the midpoint spread, wake spread and drift
  in minutes (null when unknown). No mean or target time is shown, raw or not.
- **Week review**: the sleep line gains one clause, e.g. `...; wearable says sleep times steady.`; none when
  regularity is unknown, so the line reads as before.

Synthetic example (made-up rows, today 2030-01-28 09:00 UTC, local zone UTC), produced by running
`tools.sleep` and `jobs_runner.week_sleep` on this `sleep.jsonl` (each night a little later):

```
{"night": "2030-01-18", "asleep_s": 25200, "source": "synthetic-ring", "start": "2030-01-18T22:50:00Z", "end": "2030-01-19T06:20:00Z"}
{"night": "2030-01-19", "asleep_s": 25200, "source": "synthetic-ring", "start": "2030-01-19T23:05:00Z", "end": "2030-01-20T06:35:00Z"}
{"night": "2030-01-20", "asleep_s": 25200, "source": "synthetic-ring", "start": "2030-01-20T23:20:00Z", "end": "2030-01-21T06:50:00Z"}
{"night": "2030-01-21", "asleep_s": 25200, "source": "synthetic-ring", "start": "2030-01-21T23:10:00Z", "end": "2030-01-22T06:40:00Z"}
{"night": "2030-01-22", "asleep_s": 25200, "source": "synthetic-ring", "start": "2030-01-22T23:40:00Z", "end": "2030-01-23T07:10:00Z"}
{"night": "2030-01-23", "asleep_s": 25200, "source": "synthetic-ring", "start": "2030-01-23T23:55:00Z", "end": "2030-01-24T07:25:00Z"}
{"night": "2030-01-24", "asleep_s": 25200, "source": "synthetic-ring", "start": "2030-01-25T00:15:00Z", "end": "2030-01-25T07:45:00Z"}
{"night": "2030-01-25", "asleep_s": 25200, "source": "synthetic-ring", "start": "2030-01-26T00:05:00Z", "end": "2030-01-26T07:35:00Z"}
{"night": "2030-01-26", "asleep_s": 25200, "source": "synthetic-ring", "start": "2030-01-27T00:35:00Z", "end": "2030-01-27T08:05:00Z"}
{"night": "2030-01-27", "asleep_s": 25200, "source": "synthetic-ring", "start": "2030-01-28T00:50:00Z", "end": "2030-01-28T08:20:00Z"}
```

Regularity reads all ten nights; the coverage counts are the last seven. `limitless_sleep` returns

```
{"value": {"wearable_nights": 7, "proxy_only_nights": 0, "unknown_nights": 0, "label": "sleep: wearable on most nights; phone proxy has no night to compare", "regularity": "wearable: drifting later"}, "modality": "measured", "age_h": 9.0, "evidence_tier": "direct", "label": {"label": "sleep: wearable on most nights; phone proxy has no night to compare", "tier": "T1", "modality": "measured"}}
```

with `LIMITLESS_RAW_IN_PROMPT=1` the value also has

```
"regularity_min": {"wearable": {"nights": 10, "mid_spread_min": 38, "wake_spread_min": 38, "drift_min": 117}, "proxy": {"nights": 0, "mid_spread_min": null, "wake_spread_min": null, "drift_min": null}}
```

and the week review line is `Sleep: wearable on most nights; phone proxy has no night to compare; wearable says drifting later.`

Read-only; nothing here sends.
