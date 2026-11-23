# Pre-sleep heart rate: the wearable's reading before sleep, in words

The heart rate in the stretch before sleep sits next to how the night went. `limitless/presleep_hr.py` says, in
plain words, whether last night's pre-sleep heart rate was lower than usual, about usual or higher than usual,
from the wearable only. It is observation only: no advice, no target, no score, no clock time, no drug,
supplement, caffeine or dosing note, and no push or job of its own.

- **Source** (config `presleep_hr_file`, relative to the state dir; none by default): a JSONL file, one row per
  night, `{"night": "YYYY-MM-DD", "bpm": <number>, "modality": "measured"}`. `night` is the evening the night
  began. Whatever exports the wearable's reading writes it, for example a mean over the half hour before the main
  sleep began. The public NOOP repo has such a reading in its analytics package (`PreSleepHeartRateFeedback`,
  a window before the longest sleep against a personal baseline), but it has no export or stored field to read,
  so limitless reads this file instead. `StateReader.presleep_hr_rows` reads only `night`, `bpm` and `modality`.
- **Wearable only**: only rows with `modality` `measured` are used. A phone row (or any other modality) is never
  read, not even for a night the wearable missed. A night with no valid wearable row is unknown: it is skipped,
  never zero and never filled in. A `bpm` outside 25 to 250 is not a heart rate and is skipped. The first
  wearable row of a night wins.
- **Words** (T1, no digit): the newest wearable night against the median of the fourteen wearable nights
  before it (a count of measured nights, so holes do not shrink the baseline). Within three beats per minute of
  that median is `about usual`, below it `lower than usual`, above it `higher than usual`. The band is
  `ABOUT_BPM` in code and is for the wording only, not a target or a norm. The label names the source:
  `pre-sleep heart rate about usual (wearable)`.
- **Unknown**, with a plain reason and value `null`: no wearable reading; only phone readings; fewer than five
  earlier wearable nights; or the newest wearable night more than a day and a half old (`MAX_AGE_H`, 36 h,
  counted from the local midnight after that night).
- **Tool** `limitless_presleep_hr`: the evidence envelope `{value: {label}, modality: measured, age_h,
  evidence_tier}` with the T1 label beside it. Under `LIMITLESS_RAW_IN_PROMPT=1` the value also has `bpm`,
  `baseline_bpm`, `baseline_nights` and `night`; without it no number reaches a prompt.
- **Week review**: one line after the sleep line, e.g. `Pre-sleep heart rate: about usual most nights
  (wearable).`, through `tier_audit.gate` (hook `week_review:presleep_hr`). Each of the seven nights before
  today with a wearable reading is compared with the fourteen wearable nights before it. With at least four
  compared nights, the word that holds a strict majority is the week's word, else `no clear pattern this week`.
  Fewer compared nights, phone rows only or no file: no line at all.

Synthetic example (made-up rows, today 2030-01-28 09:00 UTC, local zone UTC). Twenty earlier wearable nights
around sixty, then this week; the wearable missed 2030-01-24 and the phone row for it is ignored. Last eight
rows of `presleep-hr.jsonl`:

```
{"night": "2030-01-19", "bpm": 60, "modality": "measured"}
{"night": "2030-01-21", "bpm": 60, "modality": "measured"}
{"night": "2030-01-22", "bpm": 61, "modality": "measured"}
{"night": "2030-01-23", "bpm": 59, "modality": "measured"}
{"night": "2030-01-25", "bpm": 60, "modality": "measured"}
{"night": "2030-01-26", "bpm": 66, "modality": "measured"}
{"night": "2030-01-27", "bpm": 67, "modality": "measured"}
{"night": "2030-01-24", "bpm": 55, "modality": "proxy"}
```

`limitless_presleep_hr` returns

```
{"value": {"label": "pre-sleep heart rate higher than usual (wearable)"}, "modality": "measured", "age_h": 9.0, "evidence_tier": "direct", "label": {"label": "pre-sleep heart rate higher than usual (wearable)", "tier": "T1", "modality": "measured"}}
```

with `LIMITLESS_RAW_IN_PROMPT=1` the value is

```
{"label": "pre-sleep heart rate higher than usual (wearable)", "bpm": 67.0, "baseline_bpm": 60.0, "baseline_nights": 14, "night": "2030-01-27"}
```

the week review line is `Pre-sleep heart rate: about usual most nights (wearable).` (four of the six compared
nights), and the same file read two days later is unknown:

```
{"value": null, "modality": "measured", "age_h": 57.0, "evidence_tier": "none", "reason": "pre-sleep heart rate unknown: the newest wearable reading is more than a day and a half old"}
```

Read-only; nothing here writes or sends.
