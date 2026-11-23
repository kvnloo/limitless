# Body fat trend

A body-composition app writes one row per measurement visit. Its own estimate is fitted against reference
scans, so the trend is worth seeing once a week; the raw numbers are tier T0 and stay in code
(`limitless/body.py`). A cloud model sees the T1 words only.

- **Where**: config.json key `body_file` (a relative path is in the state dir). None by default. Rows:
  `{"day": "YYYY-MM-DD", "bf_pct": number, "method": "...", "calibrated": bool}`. A row without a real day,
  a number between 0 and 100, a method and a bool `calibrated`, or with a day after today, is skipped
  (`StateReader.body_rows()`); the reader never raises and never writes.
- **Trend**: the median of today and the 13 days before against the median of the 14 days before that.
  A change under `body_flat_points` (config, default 0.5 points) is flat. Fewer than three visits in either
  window is `not enough measurements`.
- **Modality**: `measured` when every row in both windows is calibrated, else `proxy`; the words say
  `(calibrated estimate)` or `(uncalibrated estimate)`.
- **Tool** `limitless_body`: an envelope whose value is the counts and the label; the medians and the change
  appear only with `LIMITLESS_RAW_IN_PROMPT=1` (the card's opt-in). No file or no valid row is
  `value: null` with a reason: unknown, not zero. tier_audit logs the label like any other tool result.
- **Week review**: one digit-free line after the flow line, e.g. `Body fat trending down (calibrated
  estimate).` No file or no row adds no line. The state card gets no body line.

Synthetic example (made-up rows, today 2030-01-28):

```
{"day": "2030-01-02", "bf_pct": 22.4, "method": "synthetic-scale", "calibrated": true}
{"day": "2030-01-05", "bf_pct": 22.6, "method": "synthetic-scale", "calibrated": true}
{"day": "2030-01-08", "bf_pct": 22.5, "method": "synthetic-scale", "calibrated": true}
{"day": "2030-01-17", "bf_pct": 21.4, "method": "synthetic-scale", "calibrated": true}
{"day": "2030-01-21", "bf_pct": 21.6, "method": "synthetic-scale", "calibrated": true}
{"day": "2030-01-25", "bf_pct": 21.5, "method": "synthetic-scale", "calibrated": true}
```

`limitless_body` returns
`{"value": {"recent_rows": 3, "prior_rows": 3, "label": "body fat trending down (calibrated estimate)"},
"modality": "measured", ...}`.

A direction only: no score, no goal, no target weight, no diet or supplement advice, no clock-time rule.
Nothing here sends.
