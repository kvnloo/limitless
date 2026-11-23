# Flow metrics: how broken up the work was, from observed app activity

Flow as well as the hardware can see it, without a score. Three things, per day, from the same
ActivityWatch DB copy the focus blocks use (config `aw_db`, opened read-only, cut to the not-afk time):

- how often the foreground went **from a work app to another app**, per work hour;
- the **share of work time in long blocks** (blocks of at least `break_after_min`);
- how soon **work resumed** after such a switch (the median).

This is observed app activity. It is not a measure of attention, concentration or output, and nothing
here says what is enough. No work apps, no DB or no activity row is **unknown**, never zero.

- `limitless/flow_metrics.py`: `metrics(rows, work_apps, gap_s)` (pure), `pooled(days)`, `label(m)`,
  `review_line(word)`, `thresholds(env, home)` and `read_for(...)` (every input from config).
- `limitless_flow_metrics`: the last seven days for the agent, as words.
- One line in the week review (day seven of the habit week), none when unknown.

## Definitions

A work row is an app-in-foreground span of one of your work apps: config `flow_work_apps`, the same list
and matching as `flow_week.py` and `blocks.py` (an app or package name, case-folded, or `title:<text>`
inside the window title). Days are local dates; a row is cut at midnight.

| Field | Meaning |
| --- | --- |
| `work_h` | work time (overlapping rows count once) |
| `switches` | a work row followed by a non-work row that starts less than `block_gap_min` later; several non-work rows in a row are one switch; leaving after a longer gap with no row (away) is not a switch |
| `switches_per_work_h` | switches over work hours; unknown on a day with no work time |
| `long_block_share` | work time inside blocks (work rows joined over gaps under `block_gap_min`, as `blocks.focus_blocks`) that lasted at least `break_after_min`, over all work time; `0` when there was work and no long block |
| `median_return_s` | per switch, the time from the first non-work row to the next work row on the same day, only when the activity between them has no hole of `block_gap_min` or more (a hole is a break away from the device); unknown with none |

## Words and thresholds

`label(m)` gives T1 words, no digits: **work stayed in long blocks**, **work was broken up**, **mixed**
or **unknown: \<why\>**. The thresholds are config, wording only, not targets:

| Config | Default | Reads |
| --- | --- | --- |
| `flow_long_share` | `0.6` | at least this share in long blocks ... |
| `flow_calm_switches_per_h` | `4` | ... and at most this many switches per work hour: "work stayed in long blocks" |
| `flow_broken_share` | `0.3` | less than this share in long blocks ... |
| `flow_busy_switches_per_h` | `8` | ... or more than this many switches per work hour: "work was broken up" |

Anything between is "mixed". A bad value (not a number, a share over one, zero or less) keeps its default.
The block lengths are the focus-block config: `break_after_min` (default 90) and `block_gap_min` (default
10). No rule anywhere uses a time of day.

## The tool

`limitless_flow_metrics` takes no arguments and reads the last seven days. Its value is `{days,
work_days, label}` with the T1 label beside it; modality `proxy`, evidence tier `observed-activity`
(`stale` when the newest activity row is over a day old). The numbers (`switches_per_work_h`,
`long_block_share`, `median_return_min`, `per_day`) are T0 and appear only with the raw opt-in
(`LIMITLESS_RAW_IN_PROMPT=1`). Nothing is written or sent.

## The week review line

`limitless-jobs` adds one digit-free line right after the flow line, for the habit week's seven days:
`Work pattern this week (observed app activity, not attention): <words>.` It is left out when the words are
unknown.

## Synthetic example

A made-up DB: yesterday, a long editor block with one short chat visit, then a long music visit and a
short editor run; today, six short editor runs, each left for a feed app. Work apps `["editor"]`, UTC,
the clock fixed in the evening of the second day. Real output of the tool and the review helper:

```
# limitless_flow_metrics, no raw opt-in
{"value": {"days": 2, "work_days": 2, "label": "mixed"}, "modality": "proxy", "age_h": 6.5,
 "evidence_tier": "observed-activity", "label": {"tier": "T1", "modality": "proxy", "label": "mixed"}}
# limitless_flow_metrics, LIMITLESS_RAW_IN_PROMPT=1 (value only)
{"days": 2, "work_days": 2, "label": "mixed", "switches_per_work_h": 2.44, "long_block_share": 0.54,
 "median_return_min": 15.0, "per_day": [
  {"day": "2033-05-17", "work_h": 2.28, "switches_per_work_h": 0.88, "long_block_share": 0.78,
   "median_return_min": 16.5, "label": "work stayed in long blocks"},
  {"day": "2033-05-18", "work_h": 1.0, "switches_per_work_h": 6.0, "long_block_share": 0.0,
   "median_return_min": 15.0, "label": "work was broken up"}]}
# the week review line
Work pattern this week (observed app activity, not attention): mixed.
# unknown: no work apps
{"value": null, "modality": "proxy", "age_h": null, "evidence_tier": "none",
 "reason": "flow metrics unknown: no work apps set (flow_work_apps)",
 "label": {"tier": "T1", "modality": "proxy", "label": "unknown: no work apps set (flow_work_apps)"}}
# its review line: '' (no line)
```

(The JSON is the printed output with its indentation folded; the values are unchanged.)

## Tests

`tests/test_flow_metrics.py` (the pure metrics, pooling, words and thresholds),
`tests/test_flow_metrics_tool.py` (the tool and the handler) and `tests/test_flow_metrics_review.py` (the
week review line). Synthetic rows and DBs only; nothing sends.
