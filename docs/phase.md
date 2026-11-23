# Phase: the part of the day in words, anchored on the wake event, never a clock

`limitless_phase` says which part of the day the person is in: just woke, day, evening, asleep or unknown.
It is read-only. The one thing it adds to what the agent sees is a single line on the state card while the
person has just woken ("Light: outdoor light now helps set the day."). No push, no new job, no reminder, no
clock time, no target bedtime, no light dose and no supplement advice.

- `limitless/phase.py`: `phase(wake_at, now, sleep_mode_on, posture=None)` (pure) returns the name;
  `resolve(...)` the same with its source, anchor and reason; `read_for(reader, now, env)` reads every input
  from the state dir and config (read-only).
- `limitless_phase`: an evidence envelope `{value: {phase}, modality, age_h, evidence_tier}` with a digit-free
  T1 `label`, a `why`, and `posture_ignored` when a posture file was not used.
- The state card (`pre_llm_call` and `limitless_state`): the light line while the phase is `just_woke`;
  nothing in any other phase.

## The anchor is the wake event, never a clock time

The wake is the latest wake event at or before now, the same one the wake brief and the post-wake peak use
(`jobs.wake_times` over `jobs_runner.events`: a long Sleep-mode on then off, else a screen-event wake).
Every rule is a span since an event; nothing reads a time of day.

| Phase | When | Tool words | Card |
| --- | --- | --- | --- |
| `just_woke` | from the wake event until `phase_light_h` hours after it | `just woke: a good time for outdoor light` | `Light: outdoor light now helps set the day.` |
| `day` | after that | `day: the main part of the day` | nothing |
| `evening` | once a wind-down event has happened since the wake event | `evening: wind-down part of the day` | nothing |
| `asleep` | Sleep mode is on (live poll, or turned on after the wake event) | `asleep: Sleep mode is on` | nothing |
| `unknown` | no wake event; a wake older than `MAX_AWAKE_H` or after now | `unknown: no wake event yet` (or `no recent wake event`) | nothing |

The wind-down event is the `wind_down` event in `events.jsonl` (the one the bedtime question, MIQ, fires on),
else Glide's wind-down nudge while it holds. Without one the phase stays `day` until Sleep mode goes on: there
is no evening hour.

An unknown phase is never guessed: `evidence_tier` is `none` and `reason` says why.

## Config

| Config | Default | Reads |
| --- | --- | --- |
| `phase_light_h` | `1` | how long after the wake event the phase reads `just_woke`. Wording only, not a target |
| `posture_file` (or env `LIMITLESS_POSTURE`, which wins) | none | an optional posture file written by a circadian daemon |

A bad `phase_light_h` (not a number, zero or less, a day or more) keeps the default.

## The posture file

Its schema is not public, so it is read loosely and is never required. The file is a JSON object (or a list,
whose last object is read). Only two fields are read: `phase`, a name, and `at`, when it was written (ISO-8601
or epoch seconds; without it, the file's modification time). Every other field is ignored.

It overrides the wake-based phase only when all of these hold: its `phase` is one of `just_woke`, `day`,
`evening`, `asleep` (case, spaces and hyphens are loose: `Just-Woke` reads as `just_woke`); its `at` is after
the wake event and not after now; it is not older than `MAX_AWAKE_H`; and Sleep mode is not on (live Sleep
mode always wins). Otherwise it is ignored and `posture_ignored` says why in words, for example "the posture
names something that is not a known phase" or "the posture is older than the wake event". A missing or broken
file is ignored the same way. A phase from the posture file has modality `derived`; from the wake event,
`proxy`. Both are `indirect` while fresh.

## Synthetic example

A made-up state dir: Sleep mode on in the evening and off at the wake event, no poll or digest; later a
wind-down event and a made-up posture file. Real output of `python3 -I scripts/phase_example.py`:

```text
# twenty minutes after the wake event
{"value": {"phase": "just_woke"}, "modality": "proxy", "age_h": 0.3, "evidence_tier": "indirect", "label": "just woke: a good time for outdoor light", "why": "the first part after the wake event"}
# the state card at the same moment
[limitless] state card (coarse labels; limitless_state has detail)
window: unknown
post-wake peak: open
Light: outdoor light now helps set the day.
sleep unknown (no digest in the last day); readiness unknown (no digest in the last day)
habit: none set this week

# three hours after the wake event
{"value": {"phase": "day"}, "modality": "proxy", "age_h": 3.0, "evidence_tier": "indirect", "label": "day: the main part of the day", "why": "past the first part after the wake event"}
# the state card has no light line now: True

# after the wind-down event
{"value": {"phase": "evening"}, "modality": "proxy", "age_h": 0.5, "evidence_tier": "indirect", "label": "evening: wind-down part of the day", "why": "the wind-down event has happened since the wake event"}

# a posture file fresher than the wake event
{"value": {"phase": "day"}, "modality": "derived", "age_h": 0.2, "evidence_tier": "indirect", "label": "day: the main part of the day", "why": "from the posture file, fresher than the wake event"}
# a posture file with a phase name it does not know
{"value": {"phase": "just_woke"}, "modality": "proxy", "age_h": 0.7, "evidence_tier": "indirect", "label": "just woke: a good time for outdoor light", "why": "the first part after the wake event", "posture_ignored": "the posture names something that is not a known phase"}

# no wake event
{"value": {"phase": "unknown"}, "modality": "proxy", "age_h": null, "evidence_tier": "none", "label": "unknown: no wake event yet", "why": "no wake event yet", "reason": "no wake event yet"}
```

## What it never does

- No clock time anywhere: no "before nine", no evening hour, no target bedtime. Every span starts at an event.
- No light dose, no lux, no minutes outside, no supplement or medication advice. The words name a part of the
  day; the one card line says outdoor light helps, nothing more.
- No push of its own, no new job, no reminder, no schedule card. The card line rides on the existing state
  card, which goes through `tier_audit.gate` (one content-free audit row per injection; a digit without the
  raw opt-in drops the card). A digit in the light line drops the line.
- No raw timestamps in the words: `label`, `why`, `reason` and `posture_ignored` are digit-free.
