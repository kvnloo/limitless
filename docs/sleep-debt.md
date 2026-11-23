# Sleep debt

The morning card should say, in a few words, whether the person is short on sleep. `limitless/sleep_debt.py` says
it against the person's own usual night: little sleep debt, some sleep debt or a lot of sleep debt. It wraps the
sleep readers the plugin already has; it adds no store and no data source.

## Inputs

- **The same two sources as `limitless_sleep`**: the wearable's nightly summary (`StateReader.sleep_rows`, config
  `sleep_file`) and the phone proxy, the longest quiet gap starting in the evening half of a date
  (`sleep.screen_gaps` over `jobs_runner.person_rows`). One `sleep.nights` call over the `RECENT_NIGHTS` +
  `BASELINE_NIGHTS` nights before today gives one `{night, wearable, proxy}` row per night.
- **One value per night**: the wearable's when it has the night, else the phone proxy's (a proxy night), else the
  night is unknown. An unknown night is skipped, never zero sleep, and a value of zero, below zero, a day or more,
  or not a number is unknown too.

## Rule

- The recent nights are the last `RECENT_NIGHTS` (three); the baseline is the `BASELINE_NIGHTS` (fourteen) before
  them. The usual night is the median of the baseline's known nights.
- The shortfall share is (usual night minus the mean of the recent known nights) over the usual night, floored at
  zero, so a long night is no debt. Below `SOME_SHARE` (a tenth) is "little sleep debt", from `SOME_SHARE` "some
  sleep debt", from `A_LOT_SHARE` (a quarter) "a lot of sleep debt". Both thresholds are shares of the person's
  own usual night: no population norm, no hours target.
- Fewer than `MIN_RECENT` (two) known recent nights or `MIN_BASELINE` (five) known baseline nights is "unknown:
  too few nights".
- When any night used, recent or baseline, is a proxy night, the words end in "(phone estimate)" and the modality
  is `proxy`; else it is `measured`.

## Where it shows

- **Tool** `limitless_sleep_debt`: the evidence envelope `{value: {label}, modality, age_h, evidence_tier}` with
  the T1 label beside it; `age_h` is `limitless_sleep`'s (`sleep.newest_at`). Minutes, the share and the night
  counts appear only under the raw opt-in (`LIMITLESS_RAW_IN_PROMPT=1`). Too few nights is `value: null` with the
  reason "unknown: too few nights"; no data at all is `limitless_sleep`'s missing reason.
- **State card** (`pre_llm_call`): the words on a line of their own under the sleep and readiness line, through
  the card's T1 path and `tier_audit.gate` like every other line; left out when unknown. The card never shows
  the minutes, not even under the raw opt-in.
- **Doctor**: one `tool limitless_sleep_debt` row, from the tool's own envelope like every tool in `plugin.yaml`.

Observation only: no advice, no target, no score, no clock time. Nothing is written or sent.

## Synthetic run

`python3 -I scripts/sleep_debt_example.py` (made-up nights in a temporary state dir, today 2030-01-28 09:00 UTC,
local zone UTC; fourteen baseline nights around eight hours, then three recent nights):

```text
usual night: the median of the baseline nights; some from 10% short, a lot from 25% short

recent nights near the usual:
  {"value": {"label": "little sleep debt"}, "modality": "measured", "age_h": 9.0, "evidence_tier": "direct", "label": {"label": "little sleep debt", "tier": "T1", "modality": "measured"}}

recent nights an hour short:
  {"value": {"label": "some sleep debt"}, "modality": "measured", "age_h": 9.0, "evidence_tier": "direct", "label": {"label": "some sleep debt", "tier": "T1", "modality": "measured"}}

recent nights two to three hours short:
  {"value": {"label": "a lot of sleep debt"}, "modality": "measured", "age_h": 9.0, "evidence_tier": "direct", "label": {"label": "a lot of sleep debt", "tier": "T1", "modality": "measured"}}

the same short nights under the raw opt-in:
  {"label": "some sleep debt", "baseline_median_min": 480, "recent_mean_min": 420, "short_min": 180, "short_share": 0.125, "recent_nights": 3, "unknown_nights": 0, "baseline_nights": 14, "proxy_nights": 0}

the wearable missed last night; the phone's quiet gap stands in:
  {"value": {"label": "some sleep debt (phone estimate)"}, "modality": "proxy", "age_h": 3.0, "evidence_tier": "indirect", "label": {"label": "some sleep debt (phone estimate)", "tier": "T1", "modality": "proxy"}}

the wearable has last night too; its night wins over the phone's:
  {"value": {"label": "little sleep debt"}, "modality": "measured", "age_h": 6.0, "evidence_tier": "direct", "label": {"label": "little sleep debt", "tier": "T1", "modality": "measured"}}

a gap night (neither source) is skipped, never zero (as zero it would read a lot):
  {"value": {"label": "little sleep debt"}, "modality": "measured", "age_h": 9.0, "evidence_tier": "direct", "label": {"label": "little sleep debt", "tier": "T1", "modality": "measured"}}

only three nights, no baseline:
  {"value": null, "modality": "measured", "age_h": 9.0, "evidence_tier": "none", "reason": "unknown: too few nights"}

the state card (pre_llm_call, no raw opt-in), with no digest or habit in this state dir:
  [limitless] state card (coarse labels; limitless_state has detail)
  window: unknown
  sleep unknown (no digest in the last day); readiness unknown (no digest in the last day)
  a lot of sleep debt
  habit: none set this week
```
