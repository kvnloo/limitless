# Body fat calibration against reference scans

A consumer scale's body-fat number is not trusted on its own; a reference scan (DXA) is. Before this, the
trend (`limitless/body.py`, [body-trend.md](body-trend.md)) called itself calibrated only when every row
arrived with `calibrated: true`, a flag nothing in the plugin ever set. `limitless/body_calibration.py` sets
it: it fits the scale rows to the reference scans in the same body file, corrects them, and hands the
corrected rows to the unchanged trend. Every number here is tier T0 and stays in code; a cloud model sees
the T1 words only.

## Rows

Same file, same rows as the trend (`StateReader.body_rows()`):
`{"day", "bf_pct", "method", "calibrated"}`.

- **Reference row**: `method` is in config `body_reference_methods` (a list of names, case-blind; default
  `["dxa"]`). Write it with `calibrated: true`: it is the reference and passes through unchanged, so a
  reference row written `calibrated: false` still reads as a proxy row in the trend.
- **Scale row**: any other row with `calibrated: false`. A non-reference row that already says
  `calibrated: true` (fitted outside) is left alone: never corrected twice, never paired.

## Pairing

Each reference row pairs with the scale readings of one day: the same day, else the nearest day within
config `body_pair_days` (a whole number of days, default 3). The nearest day wins; a tie between a day
before and a day after takes the earlier day. Several scale rows on that day count as their median. A
reference row with no scale day in reach makes no pair.

## The fit: the simplest model the pairs support

- **Fewer than two pairs**: no calibration. The words say so: `uncalibrated: fewer than two reference scans
  paired with a scale reading`.
- **Two or more pairs**: a constant offset, the median of (reference minus scale). One odd pair does not
  move it.
- **A line** (`reference = intercept + slope * scale`, least squares) only with five or more pairs, and only
  when its leave-one-out error (mean absolute error predicting each held-out pair from the rest) is strictly
  lower than the offset's. A slope is never taken from two, three or four points. A scale that read the same
  value every time cannot carry a line.

## Using it

`calibrated_rows(rows, fit)` is pure: a new list in which each scale row has its `bf_pct` corrected by the
fit and `calibrated: true`, its day and `method` kept; reference rows and rows already calibrated are
unchanged. No fit returns the rows as they were.

`body_calibration.trend(rows, today, env, home)` is what `limitless_body` and the week review call:

- config `body_calibration` is `on` by default, which changes something only when a fit exists. `off`
  (case-blind) is `body.trend` exactly, as before this existed. A file with no reference row is also
  exactly the old trend, with no calibration words.
- With a fit, the trend reads the calibrated rows. Where it is measured the words are `body fat trending
  down (calibrated against reference scans)` (or flat, or up).
- With reference rows but no fit, the trend is the old one and the week review line adds one sentence:
  `Uncalibrated: fewer than two reference scans paired with a scale reading.`
- `limitless_body` gains `value.calibration` (the words) and a T1 `calibration` beside the label when the file
  holds reference rows. The fit's offset, slope and errors never appear, not even under
  `LIMITLESS_RAW_IN_PROMPT=1` (which still shows the trend's medians, now of the calibrated rows).

## Synthetic example

Made-up rows, today 2030-01-28. Output of a real run (a throwaway script calling `tools.body` and
`jobs_runner.week_body` against a temp state dir):

```
body.jsonl:
  {"day": "2030-01-01", "bf_pct": 18.0, "method": "synthetic-scale", "calibrated": false}
  {"day": "2030-01-02", "bf_pct": 22.0, "method": "dxa", "calibrated": true}
  {"day": "2030-01-03", "bf_pct": 18.2, "method": "synthetic-scale", "calibrated": false}
  {"day": "2030-01-05", "bf_pct": 17.9, "method": "synthetic-scale", "calibrated": false}
  {"day": "2030-01-15", "bf_pct": 17.0, "method": "synthetic-scale", "calibrated": false}
  {"day": "2030-01-16", "bf_pct": 21.0, "method": "dxa", "calibrated": true}
  {"day": "2030-01-17", "bf_pct": 17.1, "method": "synthetic-scale", "calibrated": false}
  {"day": "2030-01-19", "bf_pct": 16.9, "method": "synthetic-scale", "calibrated": false}
T0 fit (code only): {'model': 'offset', 'pairs': 2, 'offset': 4.0}
[two scans] limitless_body value: {"recent_rows": 4, "prior_rows": 4, "label": "body fat trending down (calibrated against reference scans)", "calibration": "calibrated against reference scans"} modality: measured
[two scans] week review line: Body fat trending down (calibrated against reference scans).
[one scan] limitless_body value: {"recent_rows": 3, "prior_rows": 4, "label": "body fat trending down (uncalibrated estimate)", "calibration": "uncalibrated: fewer than two reference scans paired with a scale reading"} modality: proxy
[one scan] week review line: Body fat trending down (uncalibrated estimate). Uncalibrated: fewer than two reference scans paired with a scale reading.
[off] limitless_body value: {"recent_rows": 4, "prior_rows": 4, "label": "body fat trending down (uncalibrated estimate)"} modality: proxy
[off] week review line: Body fat trending down (uncalibrated estimate).
```

Each scan sits one day from two scale days and takes the earlier one, so both differences are four points
and the offset is four. The fit line is printed by the script from code; it is never in a label or a prompt.

A direction only: no score, no goal, no target, no advice, no clock-time rule. Nothing here writes the body
file or sends.
