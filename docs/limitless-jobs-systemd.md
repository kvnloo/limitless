# Running `bin/limitless-jobs` with a systemd user timer

`bin/limitless-jobs` makes one pass over the event-triggered jobs (wake brief, back from nap,
the bedtime question, the habit check-in) and prints one line per job. Without `--send` it is a
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
