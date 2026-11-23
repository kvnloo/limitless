# Sleep: the wearable beside a labelled phone proxy

Two sources describe sleep, and they disagree: a wearable's nightly summary (exact, but often days old) and a
phone proxy (the longest quiet gap between the person's own phone actions at night). `limitless_sleep` shows
both side by side, each with its modality and age, and never passes the proxy off as measured
(`limitless/sleep.py`). A quiet phone is time away from the phone, not sleep.

- **Wearable**: config.json key `sleep_file` (a relative path is in the state dir). None by default. JSONL rows
  `{"night": "YYYY-MM-DD", "asleep_s": int, "source": "..."}`; `night` is the evening the night began. A row
  with a bad date, a non-integer or out-of-range `asleep_s` (over zero, at most a day) or no source, a night
  after today, or a second row with the same night and source is dropped (`StateReader.sleep_rows()`; the
  first in file order is kept). Optional `start` and `end` (when the sleep began and ended) are kept as a span
  for regularity ([sleep-regularity.md](sleep-regularity.md)); other fields are never read. The reader never
  raises and never writes. `bin/limitless-noop-export --write` writes these rows (source `noop`, with `start`
  and `end`) from a NOOP database copy, wearable sessions only ([noop-export.md](noop-export.md)).
- **Phone proxy**: the same rows the screen wakes use (`screen-events.jsonl` and the optional ActivityWatch
  DB, through `jobs_runner.person_rows` and `wake_proxy.person_times`). A night's proxy is the longest quiet
  gap that starts in the evening half (noon on, local time) of its date; a gap of a day or more is a hole in
  the data, not a night.
- **Nights**: the seven nights before today. A night with neither source is unknown, never zero.
- **Words** (T1, no digit): `sleep: wearable on most nights | some nights | no nights` (most = at least 80% of
  the nights, the scorecard's bar), then `phone proxy says about the same | shorter | longer` (the median
  over nights with both of proxy minus wearable; within half an hour is about the same) or `phone proxy has
  no night to compare`.
- **Tool** `limitless_sleep`: an envelope whose value is the counts (`wearable_nights`,
  `proxy_only_nights`, `unknown_nights`) and the label. `modality` is `measured` only when the wearable
  covers the newest night, else `proxy`; `age_h` is the newest datum's age (a gap's end, or the local
  midnight after a wearable night, so a wearable night never looks fresher than it is). Per-night minutes
  appear only with `LIMITLESS_RAW_IN_PROMPT=1`. No wearable row and no phone gap is `value: null` with a reason
  that never names the path. tier_audit logs the label like any other tool result.
- **Week review**: one digit-free line after the rides line, e.g. `Sleep: wearable on most nights; phone
  proxy says longer.` No data adds no line. The state card does not change.

Synthetic example (made-up rows, today 2030-01-28 09:00 UTC, local zone UTC). `sleep.jsonl`:

```
{"night": "2030-01-21", "asleep_s": 25200, "source": "synthetic-ring"}
{"night": "2030-01-22", "asleep_s": 24600, "source": "synthetic-ring"}
{"night": "2030-01-23", "asleep_s": 26100, "source": "synthetic-ring"}
{"night": "2030-01-24", "asleep_s": 23400, "source": "synthetic-ring"}
{"night": "2030-01-25", "asleep_s": 25800, "source": "synthetic-ring"}
{"night": "2030-01-26", "asleep_s": 24900, "source": "synthetic-ring"}
{"night": "2030-01-26", "asleep_s": 20000, "source": "synthetic-ring"}
{"night": "2030-01-29", "asleep_s": 25000, "source": "synthetic-ring"}
```

`screen-events.jsonl` (unlocks at 2030-01-26 22:40, 01-27 07:10, 01-27 23:05 and 01-28 06:50 UTC):

```
{"ts": 1895697600000, "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"}
{"ts": 1895728200000, "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"}
{"ts": 1895785500000, "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"}
{"ts": 1895813400000, "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"}
```

The duplicate night and the future night are dropped; the daytime gap (07:10 to 23:05) starts in the morning
half and is no night. The wearable misses the newest night (01-27), so `limitless_sleep` returns

```
{"value": {"wearable_nights": 6, "proxy_only_nights": 1, "unknown_nights": 0,
           "label": "sleep: wearable on most nights; phone proxy says longer"},
 "modality": "proxy", "age_h": 2.2, "evidence_tier": "indirect",
 "label": {"label": "sleep: wearable on most nights; phone proxy says longer", "tier": "T1", "modality": "proxy"}}
```

and the week review line is `Sleep: wearable on most nights; phone proxy says longer.`

Two sources side by side only: no sleep target, no advice, no supplement, drug or dosing note, no clock-time
rule. Nothing here sends.
