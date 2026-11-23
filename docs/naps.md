# Naps: yesterday's short Sleep-mode periods, in words

The person sometimes takes a short daytime nap with phone Sleep mode: on, then off. The plugin already sends
"Back from nap" from the Sleep-mode off. This shows the naps together, in words only, so the morning brief and
the week review can say whether a nap sat close to the night. Observation only: no target, no streak, no advice
on when or how long to nap, no clock-time rule. Nothing here switches Sleep mode or any bedtime setting.

## What counts as a nap

`limitless/naps.py`, pure, over the Sleep-mode events from `sleepmode.jsonl` (`jobs.events_from_sleepmode`):

- Each "on" followed by an "off" is one sleep period. An "on" with no "off" yet is open, not a nap.
- A period is a nap when it is shorter than `nap_max_h` (config, default two hours) and is not the longest
  sleep period of its local day.
- A period's day is the local date it ended on, so the night that ended this morning belongs to this day. A
  short night alone in its day is the night, not a nap; a nap before a night that starts after midnight still
  counts.
- Close to the night: a nap that ended within `nap_near_night_h` (config, default four hours; wording only) of
  the start of the next period that is not a nap. With no night after it, a nap is not close.
- Unknown is never none: with no Sleep-mode change in the range, nothing is known about naps there.

`nap_max_h` is not `jobs.NAP_MAX_S` (three hours): that one decides when "Back from nap" may send; this one
decides what the ledger calls a nap. No new job and no new push: the words ride on the brief and the review.

## Where the words show

- Wake brief (`bin/limitless-brief`, `jobs_runner.brief_naps` -> `brief_post.finalize`): one line for the local
  day before the wake, e.g. "Naps yesterday: one short nap (phone Sleep mode)"; nothing when unknown.
- Week review (`jobs_runner.week_naps`, after the sleep line): one line over the seven days before the review,
  e.g. "Naps this week: a few, none close to the night (phone Sleep mode)."; nothing when unknown.
- Tool `limitless_naps`: an envelope `{value: {label}, modality: "proxy", age_h, evidence_tier}`. Sleep mode is a
  phone switch, not a sleep sensor, so it is a proxy. Start and end seconds only under
  `LIMITLESS_RAW_IN_PROMPT=1`. Read-only.

Both lines go through `tier_audit.gate` (hooks `brief:naps` and `week_review:naps`): they carry no digit, so they
are T1; a digit would be blocked without the raw opt-in.

Words: "naps yesterday: none | one short nap | a few short naps | unknown", with ", close to the night" after a
nap. Week: "none", "one, close to the night", "one, not close to the night", "a few, none / some / all close to
the night".

## Synthetic example

`python3 -I scripts/naps_example.py` (synthetic rows, UTC as the local zone; real output):

```
naps.day, yesterday:
  no nap: naps yesterday: none
  one nap after lunch: naps yesterday: one short nap
  one nap in the evening: naps yesterday: one short nap, close to the night
  two naps: naps yesterday: a few short naps
  a long afternoon sleep (not a nap): naps yesterday: none
  Sleep mode still on (open, not a nap): naps yesterday: none
  no Sleep-mode change yesterday: naps yesterday: unknown

limitless_naps:
  {"value": {"label": "naps yesterday: one short nap, close to the night"}, "modality": "proxy", "age_h": 0.5, "evidence_tier": "indirect", "label": {"label": "naps yesterday: one short nap, close to the night", "tier": "T1", "modality": "proxy"}}
limitless_naps under the raw opt-in:
  {"value": {"label": "naps yesterday: one short nap, close to the night", "naps": [{"start_s": 1899489600.0, "end_s": 1899492000.0}], "close": 1}, "modality": "proxy", "age_h": 0.5, "evidence_tier": "indirect", "label": {"label": "naps yesterday: one short nap, close to the night", "tier": "T1", "modality": "proxy"}}

wake brief line:
  Naps yesterday: one short nap, close to the night (phone Sleep mode)
week review line:
  Naps this week: one, close to the night (phone Sleep mode).
```
