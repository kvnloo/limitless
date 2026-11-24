# Push reach: the state card says when phone pushes cannot reach the person

When kevin-push's sender breaks, every push fails and is only logged, so the person never learns that pushes
stopped: the only channel that would tell them is the broken one. The `pre_llm_call` state card reaches them in
any Hermes chat instead, so it says so there, in words, on one line:

    Phone pushes are not reaching you: <reason>

and, while the owner's reply is what moves the outage on, the reply that fixes it on the same line:

    Phone pushes are not reaching you: <reason>. Reply push via <name> to fix it.

`limitless/push_reach.py` decides the reason from three facts main already has:

| Reason | When |
|---|---|
| `the sender profile was deleted` | the sender profile is missing (below) and `hermes profile delete` left its tombstone at `<Hermes home>/profiles/.deleted/<profile>` (`push_sender.tombstoned`: Hermes' marker file exists; it is never opened); restoring it brings pushes back |
| `the sender profile is missing` | `push_sender.check` is broken: kevin-push's profile (`KEVIN_PUSH_PROFILE`, else the owner's `push via <name>` reply in `push-sender.json`, else config `push_profile`) is not `default` and `<Hermes home>/profiles/<profile>` is not a directory |
| `the profile you named was set but could not send, so it may have no Telegram bot; reply push via another profile` | `push_recovery.stage` over the same log is `UNKNOWN_FAILED`: an outage is open, the owner's `push via <name>` reply was applied on an `unknown:` readiness answer (the ingest mark's `applied_unknown`, e.g. a token that may sit in a secret source) and its confirmation failed to send; held by Sleep mode or not sent yet says nothing new |
| `the last pushes failed to send` | the delivery audit of config `push_log` over the last seven local days has `send_failures` failing: the window's last transport attempts are `delivery_audit.SEND_FAIL_RUN` or more `log (telegram rc=N)` rows in a row (`delivery_audit.SEND_FAILING`) |

The rules:

- One line, never two: a deleted sender wins, then a missing one, then the named profile that could not send, then the failing
  pushes.
- No line when the sender is set and the last transport attempt was delivered, and none when neither fact can be
  told (no Hermes home, no push log set, a log that cannot be read, no row this week): unknown is silent, never
  alarming. One failure after a delivery is not yet an outage (the audit's own run length).
- Words only: no digit, no profile name, no target, no path. It never runs hermes or any process and never sends.
- On the card the line sits after the `MAX_LINES` cap, so a full card never cuts it, and before the memory
  palace and explain-back offers, which stay last. It goes through `tier_audit.gate` with the rest of the card.
- Cached with the card (`card.CardCache`): each turn only stats the config file, the profile directory and the
  push log, plus `push-sender.json`, the sender ingest and sender confirm marks and the Hermes home's `profiles`
  and `profiles/.deleted` dirs (`push_reach.key`); the config and the log are read only when the card is rebuilt.

## The reply hint (card only)

While `push_recovery.stage` over the same log is missing with `WAITING_REPLY` (no reply since the outage began),
`REFUSED` (the last reply named a profile that cannot reach Telegram) or `UNKNOWN_FAILED`, the card's line goes on
after the reason with one sentence from `push_reach.hint`:

| Ready profiles (`push_sender.candidates` says `ready`) | Words |
|---|---|
| exactly one | `Reply push via <name> to fix it.` |
| several | `Reply push via one of: <a>, <b>.` |
| none (only maybes, readiness `unknown: ...`, or none at all) | `Reply with a profile that has a Telegram bot.` |

When the sender was deleted (`push_sender.tombstoned`: a tombstone at `profiles/.deleted/<name>` and no live dir)
the hint asks to restore it first, and still offers a ready profile after it:

| Deleted sender | Words |
|---|---|
| its name has no digit | `Reply restore <name> to bring it back.` |
| its name holds a digit | `Restore the deleted sender profile to bring it back.` |
| and one / several ready profiles | `... to bring it back or reply push via <a>.` / `... or reply push via one of: <a>, <b>.` |

- A maybe is never offered as if it were sure; the sender that is failing is never offered; a name with a digit
  is never printed (if that leaves none, the generic words). Names are Hermes profile ids (no path, no host).
- Still one line, after the `MAX_LINES` cap, digit-masked with the card and through `tier_audit.gate`.
- No hint for a pending, held or failed confirmation of a ready reply (the doctor's push recovery row says
  which), when no outage is open, or when no push log can be read.
- Cached by the same key as the line: a profile added or removed changes the `profiles` dir mtime and rebuilds
  the card, and a tombstone added or restored changes the `profiles/.deleted` dir mtime. A token added to an existing profile's files shows on the next rebuild (any other key change or the
  next day). No new store and no new file.
- `limitless_status`, `limitless_state`'s `delivery` item and the context packet keep the bare reason.

## limitless_status and the context packet

`limitless_status` (`tools.status_with_delivery`) carries the same words under a `delivery` key beside its
envelope: `{"value": "<the line>", "modality": "measured", "age_h": null, "evidence_tier": "stale"}` (the
envelope's tier for an undated value: no single row dates the outage), or `value: null` with the reason
`no push outage is known`. The inputs part of the result is unchanged. `card.build` puts the same envelope in its
items as `delivery`, so `limitless_state` and the context packet carry it too: the packet's `delivery` row has
the line as its words, else `unknown: no push outage is known`.

## A real synthetic run

`python3 -I scripts/push_reach_example.py`: the synthetic fixture state, a made-up Hermes home (profile
`sender-a`, present, absent or deleted to `profiles/.deleted/`) and a made-up kevin-push log in a temporary dir, at the fixture clock in UTC.
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
Phone pushes are not reaching you: the last pushes failed to send. Reply with a profile that has a Telegram bot.
$ limitless_status: delivery
{"value": "Phone pushes are not reaching you: the last pushes failed to send", "modality": "measured", "age_h": null, "evidence_tier": "stale"}
$ limitless-context-packet: delivery row
delivery: Phone pushes are not reaching you: the last pushes failed to send (measured, stale, age unknown)

# the same, and profile helper has a Telegram bot token and chat
$ pre_llm_call card
[limitless] state card (coarse labels; limitless_state has detail)
window: peak (proxy)
sleep short (proxy); readiness low (imported)
habit this week: Lights down when wind-down starts; today Done
not recording: anki, bike, scale
asks waiting on you
Phone pushes are not reaching you: the last pushes failed to send. Reply push via helper to fix it.
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

# Hermes deleted the sender profile (profiles/.deleted/sender-a); the last pushes were not sent
$ pre_llm_call card
[limitless] state card (coarse labels; limitless_state has detail)
window: peak (proxy)
sleep short (proxy); readiness low (imported)
habit this week: Lights down when wind-down starts; today Done
not recording: anki, bike, scale
asks waiting on you
Phone pushes are not reaching you: the sender profile was deleted. Reply restore sender-a to bring it back or reply push via helper.
$ limitless_status: delivery
{"value": "Phone pushes are not reaching you: the sender profile was deleted", "modality": "measured", "age_h": null, "evidence_tier": "stale"}
$ limitless-context-packet: delivery row
delivery: Phone pushes are not reaching you: the sender profile was deleted (measured, stale, age unknown)
```
