# Decision windows (design note, draft)

## Problem

A proactive job that is correct about *what* to say can still be wrong about *when*. A
question that needs a decision lands while the person is tired; a weekly review lands in the
middle of focused work; an evening question lands at a fixed hour that happens to be the
middle of dinner on that day. Fixed clock times cannot follow a person whose day moves.

Hermes's proactivity roadmap ([#158538](https://github.com/NousResearch/hermes-agent/issues/158538),
STEP 2) asks every recurring job to state when it speaks, and for pacing that sends one
message "at the moment it matters". This note proposes a small, host-neutral way to say
"the moment it matters" without clock times.

## API

A job declares one `window_class`:

| class | meant for | example |
| --- | --- | --- |
| `peak` | a decision | "Pick one of these two plans for the week" |
| `trough` | a review or low-effort read | "Here is last week's summary" |
| `wind_down` | an end-of-day question | "Anything to capture before tomorrow?" |
| `anytime` | capture, short notes | "Saved your note" |

A `WindowProvider` reports the window open now:

```python
class WindowProvider(Protocol):
    def current(self) -> WindowState: ...

WindowState(cls="peak", since="wake", source="state_file", confidence=0.9)
```

`since` names the *event* that opened the window (woke up, focus block ended, screen off),
not a time. Providers own the event logic; the gate never reads a clock.

```python
decide(job_window_class, state, *, budget_left, asleep, critical=False)
    -> Decision(action="deliver" | "hold" | "drop", reason="<one line>")
```

Rules, in order:

1. `critical` delivers.
2. asleep holds.
3. `anytime` delivers.
4. an unknown window (no provider, unrecognised class, confidence < 0.5) holds.
5. a class mismatch holds.
6. a `peak` job with no budget left in this peak window drops: one decision per peak window;
   the job's next run may ask again. The host counts the budget and passes it in.

An invalid `window_class` is a config error (`ValueError`), so a typo fails loudly rather
than holding forever.

Two providers ship for tests and simple hosts: `StaticProvider("peak", since="wake")`, and
`StateFileProvider(path)`, which re-reads `{"cls": "peak", "since": "wake"}` on every call so
any phone automation or wearable adapter can write it. Missing or malformed files read as
unknown.

## How it maps onto Hermes

- **Schedule cards ([#158289](https://github.com/NousResearch/hermes-agent/pull/158289)).**
  `window_class` is one more field on the job record, so the "Schedule this job?" card can show
  it in words ("speaks: in a peak window, at most one decision per window"). The job keeps its
  schedule; the window decides whether a given run speaks.
- **STEP 2, "states when it speaks".** The window class *is* the "when it speaks" half; the
  existing run limit or expiry stays the "when it ends" half.
- **`[SILENT]`.** `hold` and `drop` map onto the existing silent outcome: the run produces no
  message, and the reason line belongs in the run log so a held job stays visible.
- **Pacing.** The peak budget is the "one at the moment it matters" rule, enforced per window
  rather than per day.

## Asks

A chief-of-staff agent keeps a queue of asks that need the person: approvals, decisions,
FYIs. `limitless/asks.py` is the adapter between such a queue and the window; it never
rebuilds or edits the queue. Each ask gets a class from its own fields, never from the clock:

| ask | class |
| --- | --- |
| `kind: decision`, or `kind: approval` with `effort: deep` | `peak` |
| `kind: approval` with `effort: light` (or none) | `anytime` |
| `kind: fyi` | `trough` |
| any other kind | `anytime` (never dropped) |

`plan(asks, window, sent_this_window)` returns `(ask_id, deliver | hold | fold, reason)` per ask:

1. `urgent: true` delivers whatever the window and does not count against the limit.
2. a focus block (a provider with `hold_asks`, e.g. Glide) holds everything else.
3. a `trough` ask folds into the next brief line.
4. asleep holds the rest.
5. an `anytime` ask delivers, meaning it passes to the send gate (dedupe, daily cap).
6. in a peak window, ONE `peak` ask delivers, oldest first, and only if no decision was
   delivered in that window yet; every other `peak` ask holds for the next peak window.

Reasons are plain words: the ask's title with internal card ids removed by the send gate's
`scrub`. The queue is JSONL at `LIMITLESS_ASKS` or config `asks_path`; a missing or broken
file is an empty plan. A row with `delivered_at` is done; a peak one delivered since the wake
event counts as this window's decision. `limitless_window` adds
`asks: {deliver, hold, fold, label}`, where the label is one of "one decision ready",
"decisions waiting" or "nothing waiting". Nothing here sends: the host delivers, after
which it sets `delivered_at`.

The instructions an agent follows when it wants something from the person (append one ask,
one-tap reply, let the window decide, one status board) are the plugin's `limitless:chief`
skill ([chief-skill.md](chief-skill.md)).

## Hermes cron window provider

A Hermes host whose plugin API has `ctx.register_window_provider(provider)` holds a due cron job
that declares a `window_class` until the provider says that window is open. `register(ctx)` offers
it one `limitless.window_provider.WindowProvider`; a host without that method gets nothing and one
content-free log line, so nothing changes there.

`current(now)` reads the same window `limitless_window` plans asks against (Sleep mode, the wake
event, the last unlock, a Glide focus block or wind-down, focused mode) and maps the plugin's word
to the host's class through one table:

| plugin window | host `window_class` open |
| --- | --- |
| `peak` | `peak` |
| `trough` | `trough` |
| `anytime` | `anytime` (every class opens) |
| `wind_down` | `wind_down` |
| `asleep` | none: every windowed job holds |
| `focus_block` (Glide block or focused mode) | none: every windowed job holds |
| `unknown` | none: every windowed job holds |

"None" is the host's unknown window: a job with no `window_class`, or `anytime`, still fires.
`current` reads events, never a clock time, and never raises (an error is none). Config
`window_provider` is on by default; `false` or `"off"` registers nothing.

`bin/limitless-doctor`'s `cron window provider` row tells the three cases apart: off in config, a Hermes whose
plugin API has no `register_window_provider` (config `hermes_agent_dir` names the Hermes source checkout; one
file is searched as text, Hermes is never imported), or registered, with the window the cron gate reads now
([doctor.md](doctor.md)).

## Job fields for the Hermes cron gate

The same gate stores two fields on a recurring cron job: `window_class` and `stale_after_s` (an occurrence due
longer ago than that is dropped, not sent late). `limitless.jobs.to_cron_fields(spec)` reads both from the
job's own spec through one table, `CRON_WINDOW` (`peak`, `trough`, `anytime` and `wind_down` map to the
same host class); a spec with no window gives no fields. Both need a cron or interval schedule on the host.
The schedule card (`jobs.to_schedule_card`) reads its `window` line and its `stale` line ("dropped if more than
three hours late", in number words) from these same two fields, so the card says the window and expiry the
gate enforces.

| job | `window_class` | `stale_after_s` |
| --- | --- | --- |
| wake brief | `anytime`; `peak` when it carries a decision | three hours |
| back from nap | `anytime` | one hour |
| the bedtime question (MIQ) | `wind_down` | three hours |
| habit check-in, week review | `anytime` | three hours |
| break nudge | `anytime` | six hours |
| outage recap, sender confirmation | `anytime` | twelve hours |
| the jobs that send nothing (NOOP export, the ingests) | `anytime` | none: never stale |

The event that ends a job (`expires`, e.g. Sleep mode going on) has no cron field; the plugin's own
`should_fire` still applies it.

## Creating the jobs on a patched host

`bin/limitless-cron-spec` prints the Hermes cron job each plugin job would be: one line per job in words (host
job name, title, the window it waits for, how long until a held occurrence is stale: "stale after an hour", the
same span words as the card's `stale` line, both from `jobs.span_words`), or with `--json` the payloads. It is a
dry run: it never calls Hermes, creates no job and sends nothing, and without `--scripts` it writes no file.

On the fork branch (`up/cron-decision-window-gate-r2`) the two fields can only be set through the Python job
API or a job record in `cron/jobs.json`. `hermes cron create` has no `--window-class` or `--stale-after-s`
flag, and the `cronjob` tool schema has no such field either. So each `--json` payload is the keyword
arguments for `cron.jobs.create_job(**payload)`:

| key | value | why |
| --- | --- | --- |
| `name` | `limitless-<job>` | one host job per plugin job |
| `prompt` | empty | create_job requires it. With `no_agent` the script is the whole job |
| `schedule` | `every 5m` | an interval, which is recurring, as the window fields require. The cues are events, so this only polls for them and is never the time a message is meant for |
| `no_agent`, `script` | `true`, `limitless-<job>.sh` | the job runs a script, never an agent turn. The host wants a plain file name in its scripts dir |
| `deliver` | `local` | the plugin's send gate does the sending. The host never delivers the script's output |
| `window_class`, `stale_after_s` | `jobs.to_cron_fields(spec)` | see the table above |

Jobs that send nothing (the NOOP export and the ingests) get no payload: they have no message to hold, so
`limitless-jobs --ingest` keeps running them. The wake brief's host job is `anytime`. A Hermes job's window
is fixed when the job is created, while the brief only becomes `peak` when it carries a decision, so the
plugin's own gate still holds that case.

Each host job's script runs one plugin job: `limitless-jobs --job <job>` makes the pass for that job alone, with
the same gates, marks and dry-run default as the full pass, sends only with `--send`, and prints the line the full
pass prints for that job. No other job gets a line, a mark or an ingest. An unknown name exits 2 with a usage line
that lists the names; a job that sends nothing (`--job fit_ingest`) works the same way.

To fill the scripts, run `bin/limitless-cron-spec --scripts <the host's scripts dir>`. It writes one
`limitless-<job>.sh` per payload (mode 0700, through a temp file and a rename) into that directory only. Each
script is POSIX sh and execs `"$LIMITLESS_PLUGIN_DIR/bin/limitless-jobs" --job <job> --send`, where `--send` is
the flag the systemd unit runs ([docs/limitless-jobs-systemd.md](limitless-jobs-systemd.md)). Set
`LIMITLESS_PLUGIN_DIR` to the checkout in the host job's environment; when it is unset the script exits 2 and
runs nothing. Then create each job with `cron.jobs.create_job(**payload)`.

Set config `host_scripts_dir` to that directory and `bin/limitless-doctor`'s `host job scripts` row says whether
every script is there and current, e.g. after a plugin update ([doctor.md](doctor.md#rows)).

Once the host jobs send, the systemd timer can drop `--send` and run `limitless-jobs --ingest`, so the ingests
(which have no host job) keep running. The voice MIQ is not a host job either and runs only in a full pass.
If both run anyway, a job still speaks at most once per event: the `--once` key and `jobs-sent.jsonl` see to it.
The host accepts each payload (`tests/test_cron_spec.py` runs them through copies of the fork's own rules).

## Open questions

- Should `hold` queue the message for the next matching window, or leave it to the job's
  next run? The reference gate only returns the verdict; it does not queue.
- Where should the provider live in Hermes: a config key (`cron.window_provider`), or a plugin
  hook?

Reference implementation: `limitless/decision_window.py` (stdlib only, Python 3.9+), with
`limitless/send_gate.py` taking it as an optional `window` input.
