# Breathing link: one optional slow-breathing choice in the wind-down line

Roadmap item R04 (live heart-rate and heart-rate-variability biofeedback, resonance breathing) is left to an
external app: Limitless does not build a breathing app. It only offers a link to the person's own app inside
the wind-down line it already sends, and says whether live heart data backs it. Off by default.

## Config

`wind_down_breathing_link` in `config.json`: a URL or an app deep link, for example the synthetic
`example://breathe`. Absent (the default) changes nothing. A link must be one token: a scheme, `://`, at most
two hundred printable ASCII characters, no space and no digit. A digit would make `tier_audit.gate` drop the
whole wind-down line, so a link with one is ignored and never sent; `limitless_breathing` says so in a note
without echoing it.

## The line

`limitless/wind_down.py`: `line(cfg, glide_state, night, heart_live)`. With a link set, the one wind-down line
gains ONE more choice, "slow breathing in your app", with the link at the end:

- `Screens down and lights low when you're ready, or slow breathing in your app (without heart data): example://breathe`
- with `wind_down_line` set to `off`: `Slow breathing in your app when you're ready (without heart data): example://breathe`

The words in brackets are "with live heart data" only when the wearable input is fresh by the rule
`limitless_status` already uses: `inputs.json` `ageHours.wearable` plus the snapshot's age, at most
`envelope.STALE_H` (a day). When your sync names each device's input separately, list those names in config
`wearable_inputs` (for example `["band_a", "band_b"]`; default `["wearable"]`): the freshest named input
counts. Stale, down, missing or unreadable is "without heart data". The line never holds a
breath count, a pace number, a heart rate or a heart rate variability value.

It rides in the same MIQ body as before (`jobs_runner.miq_wind_down`, hook `miq:wind_down`, through
`tier_audit.gate`): no new push, no new job, no extra send-gate call, still one line. When Glide's own
wind-down nudge already went out tonight the whole line is left out, breathing choice included. Quiet and
Sleep mode hold the whole message as before.

## The tool

`limitless_breathing` (read-only): `{value: {link_set, heart_data, link}, modality: "derived", age_h,
evidence_tier}` with a digit-free T1 label (`breathing link off`, `breathing link set, with live heart data`,
`breathing link set, without heart data`). `age_h` is the wearable input's age and `evidence_tier` that of a
measured input of that age. The link itself is shown only under `LIMITLESS_RAW_IN_PROMPT=1` (the raw_in_prompt
opt-in); otherwise `link` is "a link is set".

## Never

Suggest only: nothing here opens the link, counts breaths, sets a pace or sends. No breath count, no pace, no
heart number; no clock time (the wind-down is an event); no medical, drug, supplement or dosing words; no push
of its own; off by default.

## Example

`python3 -I scripts/breathing_link_example.py` (synthetic state in a temporary dir, a stand-in push that only
prints; nothing is sent). Its real output:

```text
$ no breathing link (the default): limitless-jobs --send (MIQ only shown)
push: MIQ for tonight?
  Your wind-down has started. Do you know the one thing that matters most tomorrow?
  Screens down and lights low when you're ready.
  Reply: Yes / No / Later
  MIQ verdict: deliver
$ limitless_breathing
{"age_h": null, "evidence_tier": "stale", "label": {"label": "breathing link off", "modality": "derived", "tier": "T1"}, "modality": "derived", "note": "a suggestion only: the wind-down line offers the person's own app by its link; nothing here opens it, counts breaths, sets a pace or sends", "value": {"heart_data": "without heart data", "link_set": false}}
$ link set, wearable input fresh: limitless-jobs --send (MIQ only shown)
push: MIQ for tonight?
  Your wind-down has started. Do you know the one thing that matters most tomorrow?
  Screens down and lights low when you're ready, or slow breathing in your app (with live heart data): example://breathe
  Reply: Yes / No / Later
  MIQ verdict: deliver
$ limitless_breathing
{"age_h": 0.9, "evidence_tier": "direct", "label": {"label": "breathing link set, with live heart data", "modality": "derived", "tier": "T1"}, "modality": "derived", "note": "a suggestion only: the wind-down line offers the person's own app by its link; nothing here opens it, counts breaths, sets a pace or sends", "value": {"heart_data": "with live heart data", "link": "a link is set", "link_set": true}}
$ limitless_breathing (LIMITLESS_RAW_IN_PROMPT=1)
{"age_h": 0.9, "evidence_tier": "direct", "label": {"label": "breathing link set, with live heart data", "modality": "derived", "tier": "T1"}, "modality": "derived", "note": "a suggestion only: the wind-down line offers the person's own app by its link; nothing here opens it, counts breaths, sets a pace or sends", "value": {"heart_data": "with live heart data", "link": "example://breathe", "link_set": true}}
$ link set, wearable input stale: limitless-jobs --send (MIQ only shown)
push: MIQ for tonight?
  Your wind-down has started. Do you know the one thing that matters most tomorrow?
  Screens down and lights low when you're ready, or slow breathing in your app (without heart data): example://breathe
  Reply: Yes / No / Later
  MIQ verdict: deliver
$ limitless_breathing
{"age_h": 30.5, "evidence_tier": "stale", "label": {"label": "breathing link set, without heart data", "modality": "derived", "tier": "T1"}, "modality": "derived", "note": "a suggestion only: the wind-down line offers the person's own app by its link; nothing here opens it, counts breaths, sets a pace or sends", "value": {"heart_data": "without heart data", "link": "a link is set", "link_set": true}}
```
