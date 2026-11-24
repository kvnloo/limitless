# Push reach: the state card says when phone pushes cannot reach the person

When kevin-push's sender breaks, every push fails and is only logged, so the person never learns that pushes
stopped: the only channel that would tell them is the broken one. The `pre_llm_call` state card reaches them in
any Hermes chat instead, so it says so there, in words, on one line:

    Phone pushes are not reaching you: <reason>

`limitless/push_reach.py` decides the reason from two facts main already has:

| Reason | When |
|---|---|
| `the sender profile is missing` | `push_sender.check` is broken: kevin-push's profile (`KEVIN_PUSH_PROFILE`, else config `push_profile`) is not `default` and `<Hermes home>/profiles/<profile>` is not a directory |
| `the last pushes failed to send` | the delivery audit of config `push_log` over the last seven local days has `send_failures` failing: the window's last transport attempts are `delivery_audit.SEND_FAIL_RUN` or more `log (telegram rc=N)` rows in a row (`delivery_audit.SEND_FAILING`) |

The rules:

- A broken sender wins when both are true: one line, never two.
- No line when the sender is set and the last transport attempt was delivered, and none when neither fact can be
  told (no Hermes home, no push log set, a log that cannot be read, no row this week): unknown is silent, never
  alarming. One failure after a delivery is not yet an outage (the audit's own run length).
- Words only: no digit, no profile name, no target, no path. It never runs hermes or any process and never sends.
- On the card the line sits after the `MAX_LINES` cap, so a full card never cuts it, and before the memory
  palace and explain-back offers, which stay last. It goes through `tier_audit.gate` with the rest of the card.
- Cached with the card (`card.CardCache`): each turn only stats the config file, the profile directory and the
  push log (`push_reach.key`); the config and the log are read only when the card is rebuilt.

## limitless_status and the context packet

`limitless_status` (`tools.status_with_delivery`) carries the same words under a `delivery` key beside its
envelope: `{"value": "<the line>", "modality": "measured", "age_h": null, "evidence_tier": "stale"}` (the
envelope's tier for an undated value: no single row dates the outage), or `value: null` with the reason
`no push outage is known`. The inputs part of the result is unchanged. `card.build` puts the same envelope in its
items as `delivery`, so `limitless_state` and the context packet carry it too: the packet's `delivery` row has
the line as its words, else `unknown: no push outage is known`.

## A real synthetic run

`python3 -I scripts/push_reach_example.py`: the synthetic fixture state, a made-up Hermes home (profile
`sender-a`, present or not) and a made-up kevin-push log in a temporary dir, at the fixture clock in UTC.
Nothing is sent and hermes never runs.

```text
# the sender profile is not in the Hermes home; the last push was delivered
$ pre_llm_call card
[limitless] state card (coarse labels; limitless_state has detail)
window: peak (proxy)
sleep short (proxy); readiness low (imported)
habit this week: Lights down when wind-down starts; today Done
not recording: anki, bike, scale
asks waiting on you
Phone pushes are not reaching you: the sender profile is missing
$ limitless_status: delivery
{"value": "Phone pushes are not reaching you: the sender profile is missing", "modality": "measured", "age_h": null, "evidence_tier": "stale"}
$ limitless-context-packet: delivery row
delivery: Phone pushes are not reaching you: the sender profile is missing (measured, stale, age unknown)

# the sender profile is there; the last two pushes logged telegram rc=1
$ pre_llm_call card
[limitless] state card (coarse labels; limitless_state has detail)
window: peak (proxy)
sleep short (proxy); readiness low (imported)
habit this week: Lights down when wind-down starts; today Done
not recording: anki, bike, scale
asks waiting on you
Phone pushes are not reaching you: the last pushes failed to send
$ limitless_status: delivery
{"value": "Phone pushes are not reaching you: the last pushes failed to send", "modality": "measured", "age_h": null, "evidence_tier": "stale"}
$ limitless-context-packet: delivery row
delivery: Phone pushes are not reaching you: the last pushes failed to send (measured, stale, age unknown)

# the sender profile is there; the last push was delivered
$ pre_llm_call card
[limitless] state card (coarse labels; limitless_state has detail)
window: peak (proxy)
sleep short (proxy); readiness low (imported)
habit this week: Lights down when wind-down starts; today Done
not recording: anki, bike, scale
asks waiting on you
$ limitless_status: delivery
{"value": null, "modality": "measured", "age_h": null, "evidence_tier": "none", "reason": "no push outage is known"}
$ limitless-context-packet: delivery row
delivery: unknown: no push outage is known (measured, none, age unknown)
```
