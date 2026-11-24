# Running `bin/limitless-jobs` with a systemd user timer

`bin/limitless-jobs` makes one pass over the event-triggered jobs (wake brief, back from nap,
the bedtime question, the habit check-in, the week review) and prints one line per job. Without `--send` it is a
dry run. With `--send`, a `deliver` verdict goes through `kevin-push` with `KEVIN_PUSH_STRICT=1`,
and the job is logged as sent (`jobs-sent.jsonl` in the state dir) only on a real Telegram delivery.

The timer below is **polling, not a clock-time rule**. It only decides how often the runner looks
for new events (Sleep mode off, a wind-down event, a habit cue). What gets sent, and when, comes
from those events, the decision window and the send gate. A run with no new event sends nothing,
and a second run after a send drops the job (`already spoke once since the wake event`). A shorter
interval means a lower delay after an event, never more messages.

The older wake-up brief sender, `bin/limitless-brief send`, now passes the same key
(`wake_brief:<wake event time in epoch seconds>`, from `jobs_runner.event_key`, the wake event
`limitless-jobs` uses) to `kevin-push`, so on one wake whichever sender gets there first is the only
brief that goes out.

## Who sends what

Each job has one owner that builds its real message. `limitless-jobs --send` never pushes a one-line
placeholder for a job another sender owns.

| Job | Sent by | With `external_jobs` naming it |
| --- | --- | --- |
| `wake_brief` (Wake-up brief) | `limitless-jobs --send` runs `bin/limitless-brief send` (the whole brief, same `wake_brief:<event time>` key). If it is missing or fails, the failure goes to stderr, nothing is sent and the job holds. | `bin/limitless-brief send` on its own schedule only |
| `nap` (Back from nap) | `limitless-jobs --send` (short text) | your own re-entry sender only (e.g. a Sleep-mode poller), with `bin/limitless-once-key nap` |
| `miq` (MIQ for tonight?) | `limitless-jobs --send` | your own wind-down sender only, with `bin/limitless-once-key miq --night` |
| `habit_checkin` (Habit check-in) | `limitless-jobs --send` | your own sender only, with `bin/limitless-once-key habit_checkin` |
| `week_review` (Week review) | `limitless-jobs --send`, on the first habit cue from day seven of a started week, once per week (key `week_review:<week_of>`): the habit, "N of M logged days" and a last line "Reply: Keep / Drop" A Keep or Drop reply is logged by `bin/limitless-habit-ingest`. | your own sender only, with `bin/limitless-once-key week_review` |

Name the jobs another sender owns in `~/.config/limitless/config.json` as `"external_jobs": ["wake_brief", "nap"]`
or in the env as `LIMITLESS_EXTERNAL_JOBS=wake_brief,nap` (the env wins). For those jobs `limitless-jobs`
still prints the verdict, with `sent by its own sender, not by limitless-jobs` in the reason, but never
pushes and never writes `jobs-sent.jsonl`. The default is empty: `limitless-jobs` sends every job.
`limitless-brief` is `$LIMITLESS_BRIEF_BIN`, else `limitless-brief` on `PATH`, else the repo's `bin/limitless-brief`.

## Older senders

A sender outside this repo (a shell script for the wind-down question, a nap notice) can ask for
the same event key with `bin/limitless-once-key <job>` (`wake_brief`, `nap`, `miq`,
`habit_checkin` or `week_review`) and pass it to `kevin-push`:

```bash
KEVIN_PUSH_ONCE=$(bin/limitless-once-key miq) kevin-push limitless "MIQ for tonight?" "..."
```

It prints `<job>:<event time>`, the key `limitless-jobs --send` passes for that event, so only the
first of the two messages goes out. With no trigger event (or state it cannot read) it prints
nothing and exits 3; `KEVIN_PUSH_ONCE` is then empty and the script sends as before, with no key.
An unknown job exits 2. It only reads the state dir; it never sends or writes.
For `miq` the key is one per night, `miq:<night date>` (the local date of the evening in the host's `TZ`, kept until the next wake), and `bin/limitless-once-key miq --night` prints it even before any wind-down event (exit 0), so a sender with its own wind-down cue always passes a key: at most one MIQ prompt per night, whoever sends.

Save as `~/.config/systemd/user/limitless-jobs.service`:

```ini
[Unit]
Description=Limitless event-triggered jobs (one pass)

[Service]
Type=oneshot
# Host specifics live in ~/.config/limitless/config.json or here as env vars, never in the repo.
# Environment=LIMITLESS_STATE=%h/.local/state/limitless
# Environment=KEVIN_PUSH_BIN=%h/src/limitless/bin/kevin-push
ExecStart=%h/src/limitless/bin/limitless-jobs --send
```

Save as `~/.config/systemd/user/limitless-jobs.timer`:

```ini
[Unit]
Description=Poll for Limitless job events every few minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=3min
AccuracySec=30s

[Install]
WantedBy=timers.target
```

Then:

```bash
bin/limitless-jobs                 # dry run first: see each job's verdict and reason
systemctl --user daemon-reload
systemctl --user enable --now limitless-jobs.timer
journalctl --user -u limitless-jobs.service -n 20
```

Change `%h/src/limitless` to wherever the repo is checked out.

## Timer: the reply ingests without sending (`--ingest`)

When sends are gated elsewhere and the timer runs `limitless-jobs` without `--send`, that plain dry run never runs
the reply ingests (`apps_ingest`, `ranked_ingest`, `sender_ingest`): their lines say `dry run of limitless-jobs: not
run`, so a `push via <profile>` reply ([push-sender-reply.md](push-sender-reply.md)) never takes effect by itself.
`--ingest` runs only those three for real, each by its own config mode (`off`: no line, `dry_run`: only the mark
is written, `write`: writes), exactly as `--send` runs them, and keeps every other job a plain dry run: it never
calls `kevin-push` or `limitless-brief`, never sends and starts no process. `--ingest --send` is `--send`.

An example service for that timer (example text only: nothing here installs or touches a unit):

```ini
[Unit]
Description=Limitless jobs pass: the reply ingests run, nothing is sent

[Service]
Type=oneshot
ExecStart=%h/src/limitless/bin/limitless-jobs --ingest
```

The timer unit above drives it as is. While a sync waits for its ingest, `limitless-doctor`'s `job apps ingest`,
`job ranked ingest` and `job sender ingest` rows say `(limitless-jobs --ingest or --send runs it)`
([doctor.md](doctor.md)).
