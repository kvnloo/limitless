# Schedule cards: every recurring job on one card

Hermes's proactivity roadmap ([#158538](https://github.com/NousResearch/hermes-agent/issues/158538)) keeps
every proactive run on a job the person approved, shown on a "Schedule this job?" card
([#158289](https://github.com/NousResearch/hermes-agent/pull/158289), read at head `dd4e675b`). STEP 2 asks
each recurring job to say when it speaks and when it ends. Limitless has six recurring jobs (wake brief,
back from nap, the bedtime question, the habit check-in, the week review, the break nudge). Each one is now
one card, so a host can show and govern it instead of the plugin running a schedule nobody sees.

`limitless/schedule_cards.py` is pure: `card_for(spec)` turns one `jobs.JobSpec` into a card, and
`cards(external=(), habit=None)` returns one card per job in `jobs.SPECS` order. Nothing in it sends,
schedules or reads a clock.

## No clock times

A card's `trigger` and `ends` are event names from `jobs.EVENTS` (`wake`, `sleep_mode_off`, `wind_down`,
`habit_cue`, `long_block`, ...), never a clock time or a cron string. `tests/test_schedule_cards.py` fails
if any card, its once-key, its description or its plain words holds a digit, a `:00` time, am/pm, a `*`, an
`@daily`-style macro or the word "every".

## Field mapping

#158289 at `dd4e675b` defines a schedule card as an approval of kind `schedule` (a new job) or
`schedule_edit` (a change). The card shows a `name` and a one-line `description` of the form
`Schedule "<name>" (<when>): <what runs>`, built from the cron job record (`schedule`, `schedule_display`,
`repeat`, `deliver`, `next_run_at`). Where it has a name for a field, the card uses it. Where it has none,
the card uses its own name, listed here.

| field | #158289 at `dd4e675b` | limitless source | meaning |
|---|---|---|---|
| `id` | job record `id` | `JobSpec.name` | stable job id (`wake_brief`, `nap`, `miq`, ...) |
| `kind` | approval `kind` (`schedule`) | constant | which card this is: a recurring job |
| `name` | card / job `name` | `JobSpec.send_title` | the title the person sees (the lane brief's `title`) |
| `description` | card `description` | `jobs.to_schedule_card` | one plain line, same `Schedule "<name>" (<when>): ...` form, digit-free |
| `trigger` | none (its `schedule` is a clock or cron string, on purpose not used) | `JobSpec.trigger_event` | the event that wakes the job |
| `ends` | none | `JobSpec.expires` | the event after which a trigger no longer counts |
| `window` | none | `JobSpec.window_class` | decision window: `peak`, `trough`, `wind_down` or `anytime` ([decision-window.md](decision-window.md)) |
| `stale_after_s` | none | `JobSpec.stale_after_s` | a trigger older than this drops the job: a late message is noise |
| `once_key` | none | `jobs_runner._key`, in words | the send gate's once-per-event key template, e.g. `miq:<night date>` |
| `budget` | none (`repeat` is a run count over the job's life, not a daily cap) | `send_gate.DAILY_CAP` | the send gate's per-day cap, shared by every limitless push |
| `per_window` | none | `JobSpec.max_per_window` | how often this job may speak per trigger |
| `sender` | none (`deliver` says where a result lands, not who sends it) | `jobs_runner.external_jobs` | `plugin` (limitless-jobs sends it), `external` (its own sender has the content) or `local` (the idea ledger: runs on this machine, sends nothing) |
| `words` | none | `jobs.to_schedule_card` | the plain lines: speaks, window, ends, delivery (and answers) |

The habit check-in and the week review follow this week's habit cue (`habit.json` `cue`), the same way
`jobs_runner.run_once` picks them. `jobs.wake_brief(decision=True)` is a `peak` card. The default spec is
`anytime`.

## The idea ledger's card

When an idea ledger is set (`LIMITLESS_IDEA_LEDGER` or config `idea_ledger`), `cards(ledger=True)` adds one
more card last: `schedule_cards.ledger_card()`, id `idea_ledger`, on the `wind_down` event, ending when Sleep
mode goes on, sender `local`, budget zero. It runs `limitless-ledger-append --write` (in `words.runs`) and sends
nothing. It is not a `jobs.SPECS` job, so `limitless-jobs` never runs it ([idea-ledger.md](idea-ledger.md)).

## The NOOP export's card

When config `noop_export` is `dry_run` or `write`, `cards(noop=True)` adds one more card last:
`schedule_cards.noop_export_card()`, id `noop_export`, on the `noop_copy` event ("after a sync that copied the
NOOP database"), ending at the next such sync, sender `local`, budget zero, once-key `noop_export:<sync run
time>`. `limitless-jobs --send` runs it (in `words.runs`); it sends nothing, so no decision window holds it. It
is not a `jobs.SPECS` job: the message jobs' cards stay as they were ([noop-export.md](noop-export.md#as-an-event-job)).

## The apps ingest's card

When config `apps_ingest` is `dry_run` or `write`, `cards(apps=True)` adds one more card last:
`schedule_cards.apps_ingest_card()`, id `apps_ingest`, on the `sync` event ("after each sync run"), ending at the
next sync run, sender `local`, budget zero, once-key `apps_ingest:<sync run time>`. It sends nothing and never
names an app ([apps-ingest.md](apps-ingest.md#as-an-event-job)).

## The ranked ingest's card

When config `ranked_ingest` is `dry_run` or `write`, `cards(ranked=True)` adds one more card last:
`schedule_cards.ranked_ingest_card()`, id `ranked_ingest`, on the `sync` event ("after each sync run"), ending at
the next sync run, sender `local`, budget zero, once-key `ranked_ingest:<sync run time>`. It sends nothing and never
names an item ([ranked-ledger.md](ranked-ledger.md#as-an-event-job)).

## The sender ingest's card

When config `sender_ingest` is `dry_run` or `write`, `cards(sender=True)` adds one more card, after the ranked
ingest's and before the outage recap's: `schedule_cards.sender_ingest_card()`, id `sender_ingest`, on the `sync`
event ("after each sync run"), ending at the next sync run, sender `local`, budget zero, once-key
`sender_ingest:<sync run time>`. It sends nothing and never names a profile
([push-sender-reply.md](push-sender-reply.md)).

## The sender confirmation's card

When config `sender_confirm` is `dry_run` or `write`, `cards(confirm=True)` adds one more card, after the sender
ingest's and before the outage recap's: `schedule_cards.sender_confirm_card()`, id `sender_confirm`, on the
`sender_changed` event ("right after your reply changes the sender for your pushes"), ending when the next reply
changes the sender again, sender `plugin`, budget the send gate's daily cap, once-key
`sender_confirm:<sender reply time>`. It never names a profile ([sender-confirm.md](sender-confirm.md)).

## The outage recap's card

When config `outage_recap` is `dry_run` or `write`, `cards(recap=True)` adds one more card last:
`schedule_cards.outage_recap_card()`, id `outage_recap`, on the `push_back` event ("when a push reaches you
again after pushes stopped getting through"), ending when pushes next come back after an outage, sender `plugin`, budget the
send gate's daily cap, once-key `outage_recap:<first failed push time>`, answers OK or More. It is not a
`jobs.SPECS` job: no decision window holds it (the delivery that wakes it shows the person can be reached), but
it goes through kevin-push's send gate like every push ([outage-recap.md](outage-recap.md)).

## Host registration

`register(ctx)` checks the host for a schedule-card method with
`hasattr(ctx, "register_schedule_card")` (`schedule_cards.HOST_METHOD`). If it is there and callable, the
plugin calls it once per card with the card dict. If not, nothing is registered and one content-free line
is logged (`schedule_cards.NO_HOST`: no job name, no digit). A host method that raises logs
`schedule_cards.HOST_FAILED` once. `register` never fails because of either.

#158289 at `dd4e675b` adds the approval card for model-created cron jobs, but no plugin ctx method for
registering one. So `register_schedule_card` is a proposed name built from the PR's own term ("schedule
card"). Every host today takes the no-op path. Renaming it is a one-line change to `HOST_METHOD`.

## The tool

`limitless_schedule` lists the cards, read-only. `value.cards` holds the raw cards, the only place digits
appear (`stale_after_s`, `budget`, `per_window`). Outside `value` there are only plain words: `lines` (one
description per card) and a T1 `label`. Both go through `tier_audit.gate` (hook `tool:limitless_schedule`,
never opted in). If a digit gets in, both are dropped and the result says why. The modality is `derived`
and `age_h` is null. Nothing is written, sent, scheduled or registered.

## Example (synthetic)

`schedule_cards.card_for(jobs.WAKE_BRIEF)`, real output:

```json
{
  "id": "wake_brief",
  "kind": "schedule",
  "name": "Wake-up brief",
  "description": "Schedule \"Wake-up brief\" (when you wake up, at most once; any time you are awake): ends when Sleep mode goes on; you, through the send gate; this job never sends by itself",
  "trigger": "wake",
  "ends": "sleep_mode_on",
  "window": "anytime",
  "stale_after_s": 10800,
  "once_key": "wake_brief:<wake event time>",
  "budget": 6,
  "per_window": 1,
  "sender": "plugin",
  "words": {
    "name": "Wake-up brief",
    "speaks": "when you wake up, at most once",
    "window": "any time you are awake",
    "ends": "when Sleep mode goes on",
    "delivery": "you, through the send gate; this job never sends by itself"
  }
}
```

The `label` and `lines` of `limitless_schedule` on the synthetic fixture state (`tests/fixtures/state`,
no config), real output:

```text
six schedule cards, each on an event, none on a clock
Schedule "Wake-up brief" (when you wake up, at most once; any time you are awake): ends when Sleep mode goes on; you, through the send gate; this job never sends by itself
Schedule "Back from nap" (when you are back from a nap, at most once; any time you are awake): ends when Sleep mode goes on; you, through the send gate; this job never sends by itself
Schedule "MIQ for tonight?" (when your wind-down starts, at most once; once your wind-down has started): ends when Sleep mode goes on; you, through the send gate; this job never sends by itself
Schedule "Habit check-in" (at your habit's cue, at most once; any time you are awake): ends when Sleep mode goes on; you, through the send gate; this job never sends by itself
Schedule "Week review" (at your habit's cue, at most once; any time you are awake): ends when Sleep mode goes on; you, through the send gate; this job never sends by itself
Schedule "Long focus block" (when a focus block runs long, at most once; any time you are awake): ends when Sleep mode goes on; you, through the send gate; this job never sends by itself
```

`tests/test_schedule_docs.py` checks both blocks against the code, so this example cannot drift.
